import argparse
import asyncio
import json
import sys
from .service import CollectorService

def main():
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='Guest-only public Douyin collector')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('collect','batch'):
        s=sub.add_parser(name); s.add_argument('refs',nargs='+'); s.add_argument('--media',action='store_true'); s.add_argument('--asr',action='store_true'); s.add_argument('--refresh',action='store_true'); s.add_argument('--max-pages',type=int,default=3); s.add_argument('--max-comments',type=int,default=50); s.add_argument('--enqueue-only',action='store_true'); s.add_argument('--source',choices=('browser','public'),default='browser')
    s=sub.add_parser('worker'); s.add_argument('--limit',type=int,default=20)
    s=sub.add_parser('search'); s.add_argument('keyword'); s.add_argument('--limit',type=int,default=20); s.add_argument('--days',type=int); s.add_argument('--enqueue-only',action='store_true'); s.add_argument('--refresh',action='store_true')
    s=sub.add_parser('status'); s.add_argument('job_id',nargs='?')
    s=sub.add_parser('export'); s.add_argument('job_id'); s.add_argument('--offset',type=int,default=0); s.add_argument('--limit',type=int,default=100)
    s=sub.add_parser('resume'); s.add_argument('job_id'); s.add_argument('--conditions-changed',action='store_true')
    sub.add_parser('recover')
    a=p.parse_args(); service=CollectorService()
    if a.command=='search':
        job=service.submit_search(a.keyword,a.limit,a.days,a.refresh)
        if not a.enqueue_only: asyncio.run(service.run_pending(limit=1))
        value=service.public_job(service.store.get_job(job['job_id']))
    elif a.command in ('collect','batch'):
        options={k:getattr(a,k) for k in ('media','asr','max_pages','max_comments','source')}
        jobs=[service.submit(r,options,a.refresh) for r in a.refs]
        if not a.enqueue_only: asyncio.run(service.run_pending(limit=len(jobs)))
        value=[service.public_job(service.store.get_job(j['job_id'])) for j in jobs]
    elif a.command=='worker': value=asyncio.run(service.run_pending(a.limit))
    elif a.command=='status': value=service.public_job(service.store.get_job(a.job_id)) if a.job_id else [service.public_job(j) for j in service.store.list_jobs()]
    elif a.command=='export': value=service.result(a.job_id,a.offset,a.limit)
    elif a.command=='resume': value=service.public_job(service.store.resume(a.job_id,conditions_changed=a.conditions_changed))
    else: value=service.recover()
    print(json.dumps(value,ensure_ascii=False,default=str,indent=2))

if __name__=='__main__': main()
