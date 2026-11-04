"""Serial, normal-UI guest collection. Never exports browser credentials."""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

def parse_video_ref(ref):
    if re.fullmatch(r'\d{15,22}', ref):
        return ref
    u = urlsplit(ref)
    if u.scheme != 'https' or u.hostname not in {'www.douyin.com', 'www.iesdouyin.com', 'jingxuan.douyin.com'} or u.username or u.password or u.port not in (None,443):
        raise ValueError('Only HTTPS public Douyin video URLs or numeric IDs are accepted')
    match = re.fullmatch(r'/(?:m/|share/)?video/(\d{15,22})/?',u.path)
    if not match:
        raise ValueError('Short links/search URLs are not yet supported; provide the canonical video URL')
    return match[1]

def classify_gate(text):
    if any(s in text for s in ('请完成下列验证','拖动滑块','安全验证','访问过于频繁')):
        return {'source':'blocked_verification'}
    result = {}
    if re.search(r'登录后(?:可)?查看更多评论',text): result['comments']='blocked_login'
    if '登录后展开更多' in text: result['replies']='blocked_login'
    if '登录后即可搜索更多精彩视频' in text: result['search']='blocked_login'
    return result

def download_allowed(detail):
    control = detail.get('video_control') or {}
    info = control.get('download_info') or {}
    return control.get('allow_download') is True and not info.get('fail_info') and info.get('level',0)==0

class GuestBrowser:
    def __init__(self, data_dir, store, *, profile=None):
        self.data_dir=Path(data_dir).resolve()
        self.store=store
        self.profile=Path(profile).resolve() if profile else self.data_dir/'guest-profile'
        self.context=None
        self.backend=None
        self.lock=None

    async def __aenter__(self):
        self.data_dir.mkdir(parents=True,exist_ok=True)
        # Filelock releases on process death; never delete a lock to steal ownership.
        from filelock import FileLock
        self.lock=FileLock(str(self.data_dir/'browser.lock'),timeout=0)
        self.lock.acquire()
        try:
            source=Path(__file__).resolve().parents[2]/'research/douyin-validation/dtk/docker'
            if not source.exists(): raise RuntimeError('Pinned v5 browser component checkout is missing')
            sys.path.insert(0,str(source))
            from browser_rpc.backends.cloak import CloakBackend
            from browser_rpc.settings import Settings
            from browser_rpc.geo import GeoProfile
            self.backend=CloakBackend(Settings(prewarm=False,geo_probe_url=None))
            await self.backend.start()
            self.context=await self.backend._launch_context(str(self.profile),GeoProfile('Asia/Shanghai','zh-CN','zh-CN,zh;q=0.9'),None,30)
            names={c['name'] for c in await self.context.cookies()}
            if names & {'sessionid','sessionid_ss','sid_guard','uid_tt'}:
                raise RuntimeError('Personal login credentials found; refuse this profile')
            return self
        except BaseException:
            await self.__aexit__(None,None,None)
            raise

    async def __aexit__(self,*exc):
        try:
            if self.context: await self.context.close()
            if self.backend: await self.backend.close()
        finally:
            if self.lock: self.lock.release()

    async def collect(self, video_id, *, max_pages=3, max_comments=50):
        from datetime import datetime,timezone
        from dtk.platforms.douyin.adapter import ADAPTER
        video_id=parse_video_ref(video_id)
        row={'video_id':video_id,'collected_at':datetime.now(timezone.utc).isoformat(),'detail':None,'nested_suggest_words':[],'comment_pages':[],'reply_pages':[], 'responses':[], 'independent_suggest_words':[], 'actions':[], 'manual_intervention':False}
        stop=asyncio.Event()
        pending=[]
        page=await self.context.new_page()
        started=time.perf_counter()
        async def capture(resp):
            path=urlsplit(resp.url).path
            if '/aweme/v1/' not in path: return
            q=parse_qs(urlsplit(resp.url).query)
            refs={k:q[k] for k in ('aweme_id','item_id','comment_id','cursor','count','from_group_id') if k in q}
            record={'path':path,'status':resp.status,'references':refs}
            row['responses'].append(record)
            if resp.status in (401,403,429):
                row['restriction']=f'HTTP {resp.status}'; stop.set()
            try:
                body=await resp.body()
                record.update(self.store.save_raw(body))
                data=json.loads(body)
                risk=ADAPTER.detect_risk_control(data)
                if risk: row['restriction']=risk; stop.set()
                detail=data.get('aweme_detail') or {}
                if str(detail.get('aweme_id'))==video_id:
                    row['detail']=detail
                    row['nested_suggest_words']=[{'json_path':'$.aweme_detail.suggest_words','value':detail['suggest_words']}] if 'suggest_words' in detail else []
                target=video_id in q.get('aweme_id',[]) or video_id in q.get('item_id',[])
                if '/comment/list/' in path:
                    entry={'target_identified':target,'references':refs,'total':data.get('total'),'cursor':data.get('cursor'),'has_more':data.get('has_more'),'comments':data.get('comments') or []}
                    row['reply_pages' if '/reply/' in path else 'comment_pages'].append(entry)
                if 'suggest_words' in path:
                    row['independent_suggest_words'].append({'references':refs,'payload':data})
            except Exception as exc: record['error_type']=type(exc).__name__
        async def inspect():
            text=await page.locator('body').inner_text(timeout=3000)
            gates=classify_gate(text)
            row['comment_gate']=gates.get('comments')=='blocked_login'
            row['reply_gate']=gates.get('replies')=='blocked_login'
            if 'source' in gates: row['restriction']=gates['source']; stop.set()
            close=page.locator('#douyin_login_comp_flat_panel_title + div')
            if not stop.is_set() and await close.count()==1 and await close.is_visible():
                await close.click(timeout=3000); row['actions'].append('closed native promotional dialog')
            return text
        def on_response(response):
            pending.append(asyncio.create_task(capture(response)))
        page.on('response',on_response)
        try:
            await page.goto('https://www.douyin.com/video/'+video_id,wait_until='domcontentloaded',timeout=30000)
            for _ in range(6):
                await inspect()
                if stop.is_set(): break
                await asyncio.sleep(1)
            seen=set()
            for _ in range(max_pages):
                await inspect()
                if stop.is_set() or row.get('comment_gate'): break
                pages=[p for p in row['comment_pages'] if p['target_identified']]
                count=len({str(c.get('cid')) for p in pages for c in p['comments'] if c.get('cid')})
                if count>=max_comments or (pages and pages[-1]['has_more']==0): break
                cursor=pages[-1]['cursor'] if pages else None
                if cursor in seen: row['pagination_stop']='cursor_stalled'; break
                seen.add(cursor)
                # Native normal page scroll, never direct cursor replay.
                await page.mouse.wheel(0,550)
                await asyncio.sleep(1.5)
            await inspect()
            if not stop.is_set() and not row.get('reply_gate'):
                controls=page.get_by_text(re.compile(r'^展开\s*\d+\s*条回复$'))
                for i in range(min(await controls.count(),3)):
                    control=controls.nth(i)
                    if await control.is_visible():
                        await control.click(timeout=3000); await asyncio.sleep(1)
                        await inspect()
                        if stop.is_set() or row.get('reply_gate'): break
            row['visible_text']=await inspect()
            row['status']='restricted' if stop.is_set() else 'observed'
        finally:
            page.remove_listener('response',on_response)
            # No new capture tasks may enter after this point. Freeze all response
            # state before returning or letting the next page/job start.
            if pending:
                try:
                    await asyncio.wait_for(asyncio.gather(*pending,return_exceptions=True),timeout=15)
                except TimeoutError:
                    for task in pending: task.cancel()
                    await asyncio.gather(*pending,return_exceptions=True)
                    row['capture_status']='error_timeout'
            await page.close()
            row['elapsed_seconds']=round(time.perf_counter()-started,3)
        return row
