"""Read actual search-page data, including server-rendered React records; never eval scripts."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote


def parse_search_html(html):
    decoder=json.JSONDecoder(); chunks=[]; documents=[]
    for match in re.finditer(r'self\.__rsc_f\.push\(',html):
        try:
            value,_=decoder.raw_decode(html,match.end())
            if isinstance(value,list) and len(value)>1 and isinstance(value[1],str): chunks.append(value[1])
        except ValueError: pass
    stream=''.join(chunks)
    for match in re.finditer(r'(?:^|\n)[0-9a-f]+:',stream):
        try:
            value,_=decoder.raw_decode(stream,match.end()); documents.append(value)
        except ValueError: pass
    # RSC text records may end immediately before the next record ID.
    # Decode JSON objects independently as data, without executing script text.
    for match in list(re.finditer(r'\{(?=")',stream))[:20000]:
        try:
            value,_=decoder.raw_decode(stream,match.start());documents.append(value)
        except ValueError:pass
    found={}
    def walk(value,depth=0):
        if depth>40:return
        if isinstance(value,dict):
            vid=value.get('aweme_id')
            if isinstance(vid,str) and re.fullmatch(r'\d{15,22}',vid) and isinstance(value.get('desc'),str):
                stats=value.get('statistics') or {};author=value.get('author') or {}
                found[vid]={'video_id':vid,'url':f'https://www.douyin.com/video/{vid}',
                    'description':value['desc'][:2000],'author':author.get('nickname') if isinstance(author,dict) else None,
                    'create_time':value.get('create_time') if type(value.get('create_time')) is int else None,
                    'statistics':{k:v for k,v in stats.items() if k in ('digg_count','comment_count','collect_count','share_count') and type(v) is int} if isinstance(stats,dict) else {},
                    'provenance':'search_page_embedded_data'}
            for child in value.values():walk(child,depth+1)
        elif isinstance(value,list):
            for child in value:walk(child,depth+1)
        elif isinstance(value,str) and value.startswith(('{','[')):
            try:walk(json.loads(value),depth+1)
            except ValueError:pass
    for document in documents:walk(document)
    return list(found.values())


def related_words(text):
    lines=[x.strip() for x in text.splitlines()];words=[]
    for i,line in enumerate(lines):
        if line in ('大家还在搜','相关搜索','猜你想搜'):
            for word in lines[i+1:i+16]:
                if not word:continue
                if word in ('更多搜索结果','抖音搜索','使用前必读','登录账号') or len(word)>30:break
                if word not in words:words.append(word)
    return words


async def search_page(context,store,keyword,limit=20,days=None):
    from .browser import classify_gate
    page=await context.new_page();responses=[]
    result={'kind':'search','keyword':keyword,'collected_at':datetime.now(timezone.utc).isoformat(),
            'ranking_scope':'observed_candidate_pool_only','videos':[]}
    def on_response(response):
        if response.status in (401,403,429):
            responses.append(response.status)
            result.update(status='blocked_verification',restriction=f'HTTP {response.status}')
    page.on('response',on_response)
    try:
        await page.set_viewport_size({'width':390,'height':844})
        main=await page.goto('https://so.douyin.com/s?keyword='+quote(keyword),wait_until='domcontentloaded',timeout=45000)
        if main and main.status in (401,403,429):
            result.update(status='blocked_verification',restriction=f'HTTP {main.status}');return result
        await page.wait_for_timeout(5000)
        text=await page.locator('body').inner_text();html=await page.content()
        result['raw_responses']=[store.save_raw(html.encode('utf-8'))]
        gate=classify_gate(text)
        # A generic footer "登录账号" is not a search login gate.
        if gate.get('source') or gate.get('search') or responses:
            result.update(status='blocked_verification' if gate.get('source') or responses else 'blocked_login',restriction=gate.get('source') or gate.get('search') or f'HTTP {responses[0]}');return result
        rows=parse_search_html(html)
        if days is not None:rows=[r for r in rows if r['create_time'] is not None and r['create_time']>=time.time()-days*86400]
        rows.sort(key=lambda r:-(r['statistics'].get('digg_count') or 0))
        result.update(status='partial' if rows else 'missing',videos=rows[:limit],observed_count=len(rows),
            stop_reason='initial_page_only' if rows else 'no_extractable_video_data',
            related_search={'status':'available' if related_words(text) else 'missing','words':related_words(text),'attribution':'keyword_search_page'})
        return result
    except Exception as exc:
        if not result.get('restriction'):result.update(status='error',error_type=type(exc).__name__)
        return result
    finally:
        page.remove_listener('response',on_response)
        try:await page.close()
        except Exception:pass
