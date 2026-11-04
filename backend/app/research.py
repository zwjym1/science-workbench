import json
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .auth import require_user
from .config import settings
from .db import get_db
from .models import Video, Comment, AnalysisJob, Topic, TopicDecision, UsageLedger, now
from .research_engine import WEIGHTS, VERSION, digest, normalize, score_evidence
from .providers import available, provider_config, reservation

router = APIRouter(dependencies=[Depends(require_user)])

class Weights(BaseModel):
    model_config = ConfigDict(extra='forbid')
    demand: float = Field(default=35, ge=0, le=100)
    evidence: float = Field(default=25, ge=0, le=100)
    explainability: float = Field(default=25, ge=0, le=100)
    freshness: float = Field(default=15, ge=0, le=100)

    @model_validator(mode='after')
    def positive(self):
        if sum(self.model_dump().values()) <= 0:
            raise ValueError('评分权重总和必须大于0')
        return self

class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    is_demo: bool
    engine: Literal['rules', 'model'] = 'rules'
    weights: Weights = Field(default_factory=Weights)

class TopicPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['candidate', 'approved', 'rejected'] | None = None
    favorite: bool | None = None
    note: str | None = Field(default=None, max_length=2000)

class MergeRequest(BaseModel):
    target_id: str

def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()

def lock_queue(db):
    # Serializes enqueue/budget/purge in this small single-user system.
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(8174201)'))
    else:
        db.execute(text('BEGIN IMMEDIATE'))

def snapshot(db, is_demo, engine):
    videos = list(db.scalars(select(Video).where(Video.is_demo == is_demo).order_by(Video.id).limit(101)))
    if len(videos) > 100:
        raise HTTPException(413, '当前分析上限100个视频，请先缩小资料范围；未静默截断数据')
    records, source_videos = [], []
    limit = 500 if engine == 'model' else 2000
    for video in videos:
        source_videos.append({'id': video.id, 'title': video.title, 'content': video.content, 'source_url': video.source_url})
        base = {'video_id': video.id, 'source_url': video.source_url, 'collected_at': iso(video.collected_at)}
        for c in db.scalars(select(Comment).where(Comment.video_id == video.id).order_by(Comment.id).limit(limit + 1)):
            records.append({**base, 'id': f'comment:{c.id}', 'kind': 'comment', 'comment_id': c.id, 'text': c.text})
        for index, search in enumerate(video.related_searches):
            records.append({**base, 'id': f'search:{video.id}:{index}', 'kind': 'search', 'text': search})
        if len(records) > limit:
            raise HTTPException(413, f'当前分析上限{limit}条评论/搜索，请拆分资料；未静默截断数据')
    if not records:
        raise HTTPException(422, '所选数据范围没有评论或相关搜索，请先导入资料')
    result = {'videos': source_videos, 'records': records}
    if engine == 'model' and len(json.dumps(result, ensure_ascii=False).encode()) > 64000:
        raise HTTPException(413, '模型输入超过64KB，请缩小资料范围')
    return result

def job_view(job):
    return {k: getattr(job, k) for k in ('id', 'status', 'stage', 'engine', 'is_demo', 'error', 'result', 'created_at', 'started_at', 'finished_at')}

def topic_view(topic):
    return {column.name: getattr(topic, column.name) for column in Topic.__table__.columns if column.name != 'fingerprint'}

def daily_spend(db, exclude_id=None):
    query = select(UsageLedger).where(UsageLedger.budget_day == now().date().isoformat())
    if exclude_id:
        query = query.where(UsageLedger.job_id != exclude_id)
    return sum(entry.estimated_cost if entry.estimated_cost is not None else entry.reserved_cost for entry in db.scalars(query))

def sync_ledger(db, job):
    if job.engine != 'model':
        return
    db.flush()
    entry = db.scalar(select(UsageLedger).where(UsageLedger.job_id == job.id))
    if entry is None:
        entry = UsageLedger(job_id=job.id)
        db.add(entry)
    for name in ('budget_day', 'reserved_cost', 'charge_state'):
        setattr(entry, name, job.result[name])
    entry.estimated_cost = job.result.get('estimated_cost')
    entry.usage = job.result.get('usage', {})

@router.get('/analysis-config')
def analysis_config():
    c = provider_config()
    return {'model_available': available(), 'provider': c['provider'], 'model': c['model'], 'scoring': '启发式排序，不预测播放量',
            'daily_budget': settings().analysis_daily_budget, 'budget_per_job': settings().analysis_budget_per_job}

@router.post('/analysis-jobs', status_code=202)
def enqueue(data: AnalysisRequest, db: Session = Depends(get_db)):
    if data.engine == 'model' and not available():
        raise HTTPException(422, '模型尚未配置：需服务端地址、模型名、密钥和单价；可以先用免费规则基线')
    lock_queue(db)
    inputs = snapshot(db, data.is_demo, data.engine)
    config = provider_config() if data.engine == 'model' else {}
    weights = data.weights.model_dump()
    key = digest({'version': VERSION, 'day': now().date().isoformat(), 'data': inputs, 'weights': weights, 'engine': data.engine, 'is_demo': data.is_demo, 'config': config})
    prior = db.scalar(select(AnalysisJob).where(AnalysisJob.digest == key))
    if prior:
        return job_view(prior)
    reserve = reservation(inputs, config) if data.engine == 'model' else 0
    if reserve > settings().analysis_budget_per_job:
        raise HTTPException(422, '预计费用预留超过单任务预算，请减少输入或调整服务端预算')
    spent = daily_spend(db)
    if reserve and reserve + spent > settings().analysis_daily_budget:
        raise HTTPException(429, '当日分析预算不足；结果不明的请求仍保留费用预留')
    job = AnalysisJob(digest=key, is_demo=data.is_demo, engine=data.engine, input_data=inputs, weights=weights, provider_config=config,
                      result={'reserved_cost': reserve, 'charge_state': 'not_sent', 'budget_day': now().date().isoformat()})
    db.add(job)
    sync_ledger(db, job)
    db.commit()
    return job_view(job)

@router.get('/analysis-jobs')
def jobs(db: Session = Depends(get_db)):
    return {'items': [job_view(job) for job in db.scalars(select(AnalysisJob).order_by(AnalysisJob.created_at.desc()).limit(100))]}

@router.get('/analysis-jobs/{job_id}')
def job_detail(job_id: str, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(404, '分析任务不存在')
    return job_view(job)

@router.post('/analysis-jobs/{job_id}/retry')
def retry_analysis(job_id: str, db: Session = Depends(get_db)):
    lock_queue(db)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, '分析任务不存在')
    if job.status == 'outcome_unknown' or job.result.get('charge_state') in ('possible', 'reported'):
        raise HTTPException(409, '此任务可能已计费，不允许自动重发；请先核对供应商用量')
    if job.status == 'failed':
        if job.engine == 'model':
            spent = daily_spend(db, job.id)
            if spent + job.result.get('reserved_cost', 0) > settings().analysis_daily_budget:
                raise HTTPException(429, '当日预算不足，暂不能重试')
            job.result = {k: v for k, v in job.result.items() if k not in ('estimated_cost', 'usage')}
            job.result = {**job.result, 'budget_day': now().date().isoformat()}
        job.status, job.stage, job.error = 'queued', '等待重试', None
        sync_ledger(db, job)
        db.commit()
    return job_view(job)

@router.get('/topics')
def topics(is_demo: bool, db: Session = Depends(get_db)):
    return {'items': [topic_view(topic) for topic in db.scalars(select(Topic).where(Topic.is_demo == is_demo).order_by(Topic.score.desc(), Topic.id).limit(300))]}

@router.patch('/topics/{topic_id}')
def patch_topic(topic_id: str, data: TopicPatch, db: Session = Depends(get_db)):
    topic = db.scalar(select(Topic).where(Topic.id == topic_id).with_for_update())
    if not topic:
        raise HTTPException(404, '选题不存在')
    if topic.status == 'merged':
        raise HTTPException(409, '已合并选题不可修改，请操作目标选题')
    changes = data.model_dump(exclude_unset=True)
    if 'status' in changes and changes['status'] is None or 'favorite' in changes and changes['favorite'] is None:
        raise HTTPException(422, '状态与收藏不可设为null')
    before = {k: getattr(topic, k) for k in changes}
    for key, value in changes.items():
        setattr(topic, key, value)
    db.add(TopicDecision(topic_id=topic.id, action='edit', detail={'before': before, 'after': changes}))
    db.commit()
    return topic_view(topic)

@router.post('/topics/{topic_id}/merge')
def merge_topic(topic_id: str, data: MergeRequest, db: Session = Depends(get_db)):
    if topic_id == data.target_id:
        raise HTTPException(422, '不能与自身合并')
    locked = list(db.scalars(select(Topic).where(Topic.id.in_([topic_id, data.target_id])).order_by(Topic.id).with_for_update()))
    by_id = {topic.id: topic for topic in locked}
    if len(locked) != 2:
        raise HTTPException(404, '选题不存在')
    source, target = by_id[topic_id], by_id[data.target_id]
    if source.is_demo != target.is_demo or source.status == 'merged' or target.status == 'merged':
        raise HTTPException(409, '不能跨真实/模拟数据合并，或选题已被合并')
    merged = {e['id']: e for e in target.evidence + source.evidence}
    target.evidence = list(merged.values())
    target.research_locked = True
    job = db.get(AnalysisJob, target.job_id)
    target.score, target.scores, target.coverage, target.support_count = score_evidence(target.evidence, job.weights)
    source.status, source.merged_into = 'merged', target.id
    db.add(TopicDecision(topic_id=source.id, action='merge', detail={'target_id': target.id}))
    db.add(TopicDecision(topic_id=target.id, action='receive_merge', detail={'source_id': source.id}))
    db.commit()
    return topic_view(target)

@router.get('/topics/{topic_id}/decisions')
def decisions(topic_id: str, db: Session = Depends(get_db)):
    return {'items': [{k: getattr(d, k) for k in ('id', 'action', 'detail', 'created_at')} for d in db.scalars(select(TopicDecision).where(TopicDecision.topic_id == topic_id).order_by(TopicDecision.created_at))]}
