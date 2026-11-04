import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def uid():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc)

class ImportJob(Base):
    __tablename__ = 'import_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    adapter: Mapped[str] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    raw_data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Video(Base):
    __tablename__ = 'videos'
    __table_args__ = (UniqueConstraint('platform', 'external_id', 'is_demo'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    platform: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    related_searches: Mapped[list] = mapped_column(JSON, default=list)

class Comment(Base):
    __tablename__ = 'comments'
    __table_args__ = (UniqueConstraint('video_id', 'external_id'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey('videos.id', ondelete='CASCADE'))
    external_id: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    likes: Mapped[int | None]

class MetricSnapshot(Base):
    __tablename__ = 'metric_snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey('videos.id', ondelete='CASCADE'))
    import_id: Mapped[str] = mapped_column(ForeignKey('import_jobs.id'))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(JSON)

class AnalysisJob(Base):
    __tablename__ = 'analysis_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean)
    engine: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default='queued')
    stage: Mapped[str] = mapped_column(String(100), default='等待分析')
    input_data: Mapped[dict] = mapped_column(JSON)
    weights: Mapped[dict] = mapped_column(JSON)
    provider_config: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Topic(Base):
    __tablename__ = 'topics'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('analysis_jobs.id'))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    engine: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default='candidate')
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    research_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    merged_into: Mapped[str | None] = mapped_column(String(36))
    evidence: Mapped[list] = mapped_column(JSON)
    support_count: Mapped[int]
    coverage: Mapped[dict] = mapped_column(JSON)
    uncertainty: Mapped[str] = mapped_column(Text)
    gap: Mapped[str] = mapped_column(Text)
    score: Mapped[float]
    scores: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class TopicDecision(Base):
    __tablename__ = 'topic_decisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'))
    action: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class UsageLedger(Base):
    """Non-content billing records survive source deletion and preserve budget limits."""
    __tablename__ = 'usage_ledger'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(String(36), unique=True)
    budget_day: Mapped[str] = mapped_column(String(10), index=True)
    reserved_cost: Mapped[float]
    estimated_cost: Mapped[float | None]
    charge_state: Mapped[str] = mapped_column(String(30))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
