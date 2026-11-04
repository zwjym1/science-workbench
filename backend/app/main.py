import json
import logging
import time
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from sqlalchemy import select, func, delete, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from .auth import check_login, token, require_user
from .config import settings
from .db import get_db
from .models import Video, Comment, MetricSnapshot, ImportJob
from .schemas import LoginRequest, ImportRequest
from .imports import digest_request, process_import
from .research import router as research_router, lock_queue
from .models import AnalysisJob, Topic, TopicDecision, UsageLedger
from .csv_adapter import CsvImportRequest, CsvAdapter
from .research_engine import digest as content_digest

app = FastAPI(title='科普创作工作台', version='0.1.0')
app.include_router(research_router)
logger = logging.getLogger('workbench')
logging.basicConfig(level=logging.INFO, format='%(message)s')

@app.middleware('http')
async def request_log(request: Request, call_next):
    start = time.monotonic()
    # JSON imports are intentionally bounded for the synchronous M1 path.
    if request.method == 'POST':
        body = await request.body()
        if len(body) > 5 * 1024 * 1024:
            return Response('请求不得超过 5MB', status_code=413)
    response = await call_next(request)
    logger.info(json.dumps({'event': 'http', 'method': request.method, 'path': request.url.path, 'status': response.status_code, 'duration_ms': round((time.monotonic()-start)*1000)}, ensure_ascii=False))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.get('/health')
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {'status': 'ok'}

@app.post('/auth/login')
def login(data: LoginRequest, request: Request, response: Response):
    check_login(request, data.password)
    response.set_cookie('session', token(), httponly=True, secure=settings().cookie_secure, samesite='strict', max_age=settings().session_hours * 3600, path='/')
    return {'user': 'admin'}

@app.get('/auth/me', dependencies=[Depends(require_user)])
def me():
    return {'user': 'admin'}

@app.post('/auth/logout')
def logout(response: Response):
    response.delete_cookie('session', path='/')
    return {'ok': True}

def fields(obj, keys):
    result = {key: getattr(obj, key) for key in keys}
    return {key: value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value for key, value in result.items()}

def job_view(job):
    return fields(job, ('id', 'adapter', 'is_demo', 'status', 'result', 'error', 'created_at'))

def execute_job(db, job):
    job = db.scalar(select(ImportJob).where(ImportJob.id == job.id).with_for_update())
    if job.status == 'succeeded':
        return job_view(job)
    try:
        process_import(db, job)
        db.commit()
    except Exception:
        db.rollback()
        job = db.get(ImportJob, job.id)
        job.status = 'failed'
        job.error = '标准化失败，可重试；请检查服务端日志'
        db.commit()
        logger.exception(json.dumps({'event': 'import_failed', 'job_id': job.id}))
    return job_view(job)

@app.post('/imports', dependencies=[Depends(require_user)])
async def import_data(data: ImportRequest, request: Request, db: Session = Depends(get_db)):
    raw = await request.json()
    return await run_in_threadpool(store_import, data, raw, db)

def store_import(data, raw, db):
    digest = digest_request(data)
    return store_raw_import(db, digest, data.adapter, data.is_demo, raw['data'])

@app.post('/imports/csv', dependencies=[Depends(require_user)])
def import_csv(data: CsvImportRequest, db: Session = Depends(get_db)):
    raw = {'csv_text': data.csv_text, 'mapping': data.mapping}
    try:
        CsvAdapter().normalize(raw)
    except (ValueError, TypeError):
        raise HTTPException(422, 'CSV校验失败：请检查必填列、时间时区、数字、稳定评论ID及相同视频元数据的一致性') from None
    return store_raw_import(db, content_digest({'adapter': 'standard-csv', 'is_demo': data.is_demo, 'raw': raw}), 'standard-csv', data.is_demo, raw)

def store_raw_import(db, digest, adapter, is_demo, raw):
    existing = db.scalar(select(ImportJob).where(ImportJob.digest == digest))
    if existing:
        return job_view(existing)
    job = ImportJob(digest=digest, adapter=adapter, is_demo=is_demo, raw_data=raw)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return job_view(db.scalar(select(ImportJob).where(ImportJob.digest == digest)))
    return execute_job(db, job)

@app.get('/imports', dependencies=[Depends(require_user)])
def list_imports(db: Session = Depends(get_db)):
    return {'items': [job_view(x) for x in db.scalars(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(100))]}

@app.post('/imports/{job_id}/retry', dependencies=[Depends(require_user)])
def retry(job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, '任务不存在')
    if job.status == 'succeeded':
        return job_view(job)
    return execute_job(db, job)

@app.get('/videos', dependencies=[Depends(require_user)])
def videos(q: str = '', is_demo: bool | None = None, platform: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = select(Video)
    if q:
        query = query.where(or_(Video.title.icontains(q), Video.content.icontains(q)))
    if is_demo is not None:
        query = query.where(Video.is_demo == is_demo)
    if platform:
        query = query.where(Video.platform == platform)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = []
    for video in db.scalars(query.order_by(Video.collected_at.desc()).limit(limit).offset(offset)):
        item = fields(video, ('id', 'platform', 'external_id', 'title', 'source_url', 'published_at', 'collected_at', 'is_demo', 'tags'))
        item['comments_count'] = db.scalar(select(func.count()).select_from(Comment).where(Comment.video_id == video.id))
        items.append(item)
    return {'items': items, 'total': total}

@app.get('/videos/{video_id}', dependencies=[Depends(require_user)])
def detail(video_id: str, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, '视频不存在')
    return {'video': fields(video, [c.name for c in Video.__table__.columns]), 'comments': [{'id': c.id, 'text': c.text, 'likes': c.likes} for c in db.scalars(select(Comment).where(Comment.video_id == video_id))], 'snapshots': [fields(s, ('collected_at', 'metrics')) for s in db.scalars(select(MetricSnapshot).where(MetricSnapshot.video_id == video_id))]}

@app.delete('/library', dependencies=[Depends(require_user)])
def purge(is_demo: bool, db: Session = Depends(get_db)):
    lock_queue(db)
    if db.scalar(select(AnalysisJob.id).where(AnalysisJob.is_demo == is_demo, AnalysisJob.status == 'running').limit(1)):
        raise HTTPException(409, '分析仍在运行，请完成后再删除资料')
    topic_ids = select(Topic.id).where(Topic.is_demo == is_demo)
    db.execute(delete(TopicDecision).where(TopicDecision.topic_id.in_(topic_ids)))
    db.execute(delete(Topic).where(Topic.is_demo == is_demo))
    queued_ids = select(AnalysisJob.id).where(AnalysisJob.is_demo == is_demo, AnalysisJob.status == 'queued')
    db.query(UsageLedger).filter(UsageLedger.job_id.in_(queued_ids)).update({'estimated_cost': 0, 'charge_state': 'cancelled'}, synchronize_session=False)
    db.execute(delete(AnalysisJob).where(AnalysisJob.is_demo == is_demo))
    ids = select(Video.id).where(Video.is_demo == is_demo)
    db.execute(delete(Comment).where(Comment.video_id.in_(ids)))
    db.execute(delete(MetricSnapshot).where(MetricSnapshot.video_id.in_(ids)))
    db.execute(delete(Video).where(Video.is_demo == is_demo))
    db.execute(delete(ImportJob).where(ImportJob.is_demo == is_demo))
    db.commit()
    return {'deleted': True, 'is_demo': is_demo}
