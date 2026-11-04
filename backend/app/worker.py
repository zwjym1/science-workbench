"""Durable DB queue: one small worker, atomic claims, no volatile in-process tasks."""
import argparse
import logging
import time
from datetime import timedelta, timezone
from sqlalchemy import select, update
from .db import SessionLocal
from .models import AnalysisJob, Topic, now
from .research_engine import rule_clusters, grounded_topics, digest, normalize
from . import providers
from .config import settings
from .research import lock_queue, daily_spend, sync_ledger

logger = logging.getLogger('workbench.worker')
logging.basicConfig(level=logging.INFO, format='%(message)s')

def recover_stale(db):
    cutoff = now() - timedelta(seconds=settings().analysis_timeout * 3 + 180)
    for job in db.scalars(select(AnalysisJob).where(AnalysisJob.status == 'running', AnalysisJob.started_at < cutoff).with_for_update()):
        job.status = 'outcome_unknown' if job.engine == 'model' else 'queued'
        job.stage = '进程中断，需核对模型用量' if job.engine == 'model' else '已恢复排队'
        job.error = '上次运行未完成；模型请求可能已经计费' if job.engine == 'model' else None
    db.commit()

def run_once(session_factory=SessionLocal):
    with session_factory() as db:
        recover_stale(db)
        lock_queue(db)
        candidate = db.scalar(select(AnalysisJob.id).where(AnalysisJob.status == 'queued').order_by(AnalysisJob.created_at, AnalysisJob.id).limit(1))
        if not candidate:
            return False
        pending = db.get(AnalysisJob, candidate)
        if pending.engine == 'model' and pending.result.get('budget_day') != now().date().isoformat():
            if daily_spend(db, pending.id) + pending.result.get('reserved_cost', 0) > settings().analysis_daily_budget:
                pending.status, pending.stage, pending.error = 'failed', '预算不足', '跨日执行时当日预算不足；未调用模型'
                pending.result = {**pending.result, 'estimated_cost': 0, 'charge_state': 'not_sent'}
                sync_ledger(db, pending)
                db.commit()
                return True
            pending.result = {**pending.result, 'budget_day': now().date().isoformat()}
            sync_ledger(db, pending)
        claimed = db.execute(update(AnalysisJob).where(AnalysisJob.id == candidate, AnalysisJob.status == 'queued').values(status='running', started_at=now(), stage='归组与来源校验'))
        db.commit()
        if claimed.rowcount != 1:
            return False
        job = db.get(AnalysisJob, candidate)
        try:
            skipped = 0
            if job.engine == 'model':
                if not providers.available() or providers.provider_config() != job.provider_config:
                    raise providers.ProviderRejected('服务端模型配置已改变或不可用，请恢复原配置后重试')
                job.result = {**job.result, 'charge_state': 'possible'}
                sync_ledger(db, job)
                db.commit()  # Mark before the external side effect.
                response = providers.ADAPTERS[job.provider_config['provider']].request(job.provider_config, providers.prompt_for(job.input_data), settings().analysis_api_key)
                cost = providers.estimated_cost(response['usage'], job.provider_config)
                job.result = {**job.result, 'usage': response['usage'], 'charge_state': 'reported'}
                if cost is not None:
                    job.result = {**job.result, 'estimated_cost': cost}
                sync_ledger(db, job)
                db.commit()  # Keep usage even if grounding validation fails.
                output = providers.AnalysisOutput.model_validate_json(response['text'])
                groups = [group.model_dump() for group in output.topics]
                ids = [identifier for group in groups for identifier in group['evidence_ids']]
                if len(ids) != len(set(ids)):
                    raise ValueError('模型将同一来源重复计入多个选题')
            else:
                groups, skipped = rule_clusters(job.input_data['records'])
            if len({normalize(group['question']) for group in groups}) != len(groups):
                raise ValueError('模型重复输出相同问题')
            topics = grounded_topics(groups, job.input_data['records'], job.weights, job.engine, job.created_at.replace(tzinfo=timezone.utc))
            for result in topics:
                fingerprint = digest({'demo': job.is_demo, 'question': normalize(result['question'])})
                topic = db.scalar(select(Topic).where(Topic.fingerprint == fingerprint).with_for_update())
                if topic is None:
                    db.add(Topic(fingerprint=fingerprint, job_id=job.id, is_demo=job.is_demo, engine=job.engine, **result))
                elif topic.status == 'candidate' and not topic.research_locked:
                    # Preserve human decisions/favorites; approved/rejected/merged cards are immutable to analysis.
                    for key, value in result.items():
                        setattr(topic, key, value)
                    topic.job_id, topic.engine = job.id, job.engine
            job.status, job.stage, job.error, job.finished_at = 'succeeded', '分析完成', None, now()
            job.result = {**job.result, 'topics_generated': len(topics), 'records_received': len(job.input_data['records']), 'filtered_noise_records': skipped,
                          'scope': {'videos': len(job.input_data['videos']), 'comments': sum(e['kind'] == 'comment' for e in job.input_data['records']), 'searches': sum(e['kind'] == 'search' for e in job.input_data['records'])}}
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(AnalysisJob, candidate)
            if not job:
                return True
            if isinstance(exc, providers.ProviderRejected):
                job.result = {**job.result, 'charge_state': 'not_sent', 'estimated_cost': 0}
                message = str(exc)
            elif isinstance(exc, providers.OutcomeUnknown):
                message = str(exc)
            else:
                message = '结果校验或保存失败；未发布分析结论，请检查服务端日志'
                logger.error('analysis_failed job_id=%s type=%s', candidate, type(exc).__name__)
            job.status = 'outcome_unknown' if isinstance(exc, providers.OutcomeUnknown) else 'failed'
            job.stage, job.error, job.finished_at = '分析中止', message, now()
            sync_ledger(db, job)
            db.commit()
        return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    while True:
        try:
            worked = run_once()
        except Exception as exc:
            logger.error('worker_error type=%s', type(exc).__name__)
            worked = False
        if args.once:
            break
        if not worked:
            time.sleep(2)

if __name__ == '__main__':
    main()
