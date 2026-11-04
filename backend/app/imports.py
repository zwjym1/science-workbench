import hashlib
import json
from datetime import timezone
from sqlalchemy import select
from .models import ImportJob, Video, Comment, MetricSnapshot
from .adapters import ADAPTERS

def digest_request(request):
    return hashlib.sha256(json.dumps(request.model_dump(mode='json', exclude_unset=True), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def process_import(db, job):
    """One transaction: a failed import cannot leave partially normalized data."""
    data = ADAPTERS[job.adapter].normalize(job.raw_data)
    created = comments = 0
    for item in data.videos:
        video = db.scalar(select(Video).where(Video.platform == item.platform, Video.external_id == item.external_id, Video.is_demo == job.is_demo))
        latest = True
        if video is not None:
            previous_time = video.collected_at
            if previous_time.tzinfo is None:  # SQLite stores timezone-aware values as UTC-naive.
                previous_time = previous_time.replace(tzinfo=timezone.utc)
            latest = item.collected_at >= previous_time
        if video is None:
            video = Video(platform=item.platform, external_id=item.external_id, is_demo=job.is_demo)
            db.add(video)
            created += 1
        for key in ('title', 'content', 'published_at', 'collected_at', 'tags', 'related_searches'):
            if latest and (key in item.model_fields_set or video.id is None):
                setattr(video, key, getattr(item, key))
        if latest:
            video.source_url = str(item.source_url)
        db.flush()
        for c in item.comments:
            existing = db.scalar(select(Comment).where(Comment.video_id == video.id, Comment.external_id == c.external_id))
            if existing is None:
                db.add(Comment(video_id=video.id, **c.model_dump()))
                db.flush()
                comments += 1
            elif latest:
                existing.text = c.text
                if 'likes' in c.model_fields_set:
                    existing.likes = c.likes
        db.add(MetricSnapshot(video_id=video.id, import_id=job.id, collected_at=item.collected_at, metrics=item.metrics))
    job.status = 'succeeded'
    job.error = None
    job.result = {'videos_created': created, 'comments_created': comments, 'videos_received': len(data.videos)}
