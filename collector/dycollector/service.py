"""Shared job orchestration for CLI and MCP. No model calls."""
import asyncio
import os
import json
from pathlib import Path
from .browser import GuestBrowser, parse_video_ref
from .normalize import normalize_capture
from .store import Store

class CollectorService:
    def __init__(self,database_url=None,data_dir=None):
        self.data_dir=Path(data_dir or os.environ.get('COLLECTOR_DATA_DIR',Path(__file__).resolve().parents[1]/'data')).resolve()
        self.data_dir.mkdir(parents=True,exist_ok=True)
        url=database_url or os.environ.get('COLLECTOR_DATABASE_URL')
        if not url: url='sqlite:///'+str(self.data_dir/'collector.sqlite')
        self.store=Store(url,self.data_dir)

    def submit(self,ref,options=None,refresh=False):
        vid=parse_video_ref(ref)
        supplied=options or {}
        if set(supplied)-{'max_pages','max_comments','media','asr','ocr','source'}: raise ValueError('Unknown collection option')
        options={'max_pages':3,'max_comments':50,'media':False,'asr':False,'ocr':False,**supplied}
        for name,maximum in [('max_pages',20),('max_comments',500)]:
            if type(options[name]) is not int or not 1<=options[name]<=maximum: raise ValueError(f'{name} outside supported range')
        for name in ('media','asr','ocr'):
            if type(options[name]) is not bool: raise ValueError(f'{name} must be boolean')
        if options['asr'] and not options['media']: raise ValueError('ASR requires media=true')
        if options.get('source','browser') not in ('browser','public'): raise ValueError('Unknown source')
        return self.store.submit(vid,options=options,refresh=refresh)

    def submit_search(self,keyword,limit=20,days=None,refresh=False):
        import hashlib
        if not isinstance(keyword,str) or not 1<=len(keyword.strip())<=100: raise ValueError('Keyword must be 1..100 characters')
        if type(limit) is not int or not 1<=limit<=50: raise ValueError('limit must be 1..50')
        if days is not None and (type(days) is not int or not 1<=days<=365): raise ValueError('days must be 1..365')
        keyword=keyword.strip()
        return self.store.submit('search:'+hashlib.sha256(keyword.encode()).hexdigest()[:32],options={'kind':'search','keyword':keyword,'limit':limit,'days':days},refresh=refresh)

    async def run_pending(self,limit=20):
        completed=[]
        # claim inside profile ownership to prevent a second worker failing jobs.
        async with GuestBrowser(self.data_dir,self.store,profile=os.environ.get('COLLECTOR_GUEST_PROFILE')) as browser:
            self.store.recover_interrupted()
            for _ in range(limit):
                job=self.store.claim_next()
                if not job: break
                job_id=job['job_id']
                try:
                    options=job.get('options') or {}
                    if options.get('kind')=='search':
                        from .search import search_page
                        result=await search_page(browser.context,self.store,options['keyword'],options['limit'],options.get('days'))
                        if result.get('restriction'):
                            self.store.pause(job_id,result['restriction'],result=result);break
                        self.store.finish(job_id,result,state='failed' if result.get('status')=='error' else 'partial');completed.append(job_id);continue
                    source=browser
                    if options.get('source')=='public':
                        from .public_api import PublicAPI
                        source=PublicAPI(self.store,browser.context)
                    row=await source.collect(job['video_id'],max_pages=options.get('max_pages',3),max_comments=options.get('max_comments',50))
                    try:
                        result=normalize_capture(row)
                    except Exception:
                        if not row.get('restriction'): raise
                        result={'video_id':job['video_id'],'normalization_status':'error','restriction':str(row['restriction'])}
                    result['raw_responses']=[r for r in row['responses'] if r.get('sha256')]
                    result['metrics']=result.get('detail',{}).get('statistics') or {}
                    if row.get('restriction'):
                        self.store.pause(job_id,str(row['restriction']),result=result)
                        # Do not process another queued task after a source restriction.
                        break
                    from .content import extract_content
                    result['content']=await extract_content(row.get('detail') or {},browser.context,self.data_dir/'media'/job_id,options)
                    if any(isinstance(v,dict) and v.get('http_status') in (401,403,429) for v in result['content'].values()):
                        self.store.pause(job_id,'content HTTP access restriction',result=result)
                        break
                    required=[result.get(k,{}).get('status') for k in ('detail','comments','replies')]
                    if options.get('media'): required.append(result['content']['media']['status'])
                    if options.get('asr'): required.append(result['content']['asr']['status'])
                    if options.get('ocr'): required.append(result['content']['ocr']['status'])
                    state='succeeded' if all(s in ('available','observed_empty','not_requested') for s in required) else 'partial'
                    self.store.finish(job_id,result,state=state)
                    completed.append(job_id)
                except Exception as exc:
                    # Error messages can include signatures; expose type only.
                    self.store.finish(job_id,{'error_type':type(exc).__name__},state='failed')
        return completed

    def recover(self):
        from filelock import FileLock
        with FileLock(str(self.data_dir/'browser.lock'),timeout=0):
            return self.store.recover_interrupted()

    def public_job(self,job):
        if job is None: raise ValueError('Job not found')
        return {k:job[k] for k in ('job_id','video_id','state','options','created_at','updated_at','collected_at','cache_age','is_cached','pause_reason') if k in job}

    def result(self,job_id,offset=0,limit=20):
        if offset<0 or not 1<=limit<=100: raise ValueError('Invalid pagination')
        job=self.store.get_job(job_id)
        if not job: raise ValueError('Job not found')
        result=dict(job.get('result') or {})
        result.pop('raw_responses',None)
        if isinstance(result.get('videos'),list):
            videos=result['videos'];result['videos']=videos[offset:offset+limit]
            result['returned_offset']=offset;result['total_saved_videos']=len(videos)
        for key in ('comments','replies'):
            block=result.get(key)
            if isinstance(block,dict):
                block=dict(block); all_items=block.get('items') or []; block['items']=all_items[offset:offset+limit]; block['returned_offset']=offset; result[key]=block
        # Public serialization has independent character/item/depth and whole
        # response budgets. Persisted evidence is not truncated.
        def bounded(value,depth=0):
            if depth>12: return '[depth limit]'
            if isinstance(value,str): return value[:2000]+(' [truncated]' if len(value)>2000 else '')
            if isinstance(value,list): return [bounded(v,depth+1) for v in value[:limit]]
            if isinstance(value,dict):
                return {str(k)[:100]:bounded(v,depth+1) for k,v in list(value.items())[:100]}
            return value
        public=bounded(result)
        if len(json.dumps(public,ensure_ascii=False))>60000:
            return {'video_id':result.get('video_id'),'status':'response_budget_exceeded','message':'Use a smaller limit; full evidence remains local.'}
        return public
