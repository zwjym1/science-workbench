"""Durable job store. SQLite tests and PostgreSQL use the same schema."""
import hashlib
import json
import os
import tempfile
import time
import uuid
import re
from pathlib import Path

from sqlalchemy import (Column, Float, Integer, JSON, MetaData, String, Table,
                        create_engine, select, update)
from sqlalchemy.pool import NullPool
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()
schema_versions = Table('collector_schema_versions', metadata, Column('version', Integer, primary_key=True))
keys = Table('collector_keys', metadata, Column('key', String(64), primary_key=True))
jobs = Table('collector_jobs', metadata,
    Column('job_id', String(36), primary_key=True), Column('key', String(64), nullable=False, index=True),
    Column('video_id', String(64), nullable=False, index=True), Column('options', JSON, nullable=False),
    Column('state', String(24), nullable=False, index=True), Column('created_at', Float, nullable=False),
    Column('updated_at', Float, nullable=False), Column('collected_at', Float),
    Column('pause_reason', String), Column('result', JSON))
raw_responses = Table('collector_raw_responses', metadata,
    Column('job_id', String(36), primary_key=True), Column('sha256', String(64), primary_key=True),
    Column('path', String, nullable=False), Column('size', Integer, nullable=False))
snapshots = Table('collector_snapshots', metadata,
    Column('job_id', String(36), primary_key=True), Column('video_id', String(64), nullable=False),
    Column('collected_at', Float, nullable=False), Column('metrics', JSON, nullable=False))

class Store:
    cache_ttl_seconds = 3600

    def __init__(self, database_url, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        kwargs = {'connect_args': {'timeout': 30}} if database_url.startswith('sqlite:') else {}
        if database_url.startswith('sqlite:') and ':memory:' not in database_url:
            kwargs['poolclass'] = NullPool
        self.engine = create_engine(database_url, **kwargs)
        if self.engine.dialect.name not in ('sqlite', 'postgresql'):
            raise ValueError('Only SQLite and PostgreSQL are supported')
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            self._insert_ignore(conn, schema_versions, {'version': 1})

    def _insert_ignore(self, conn, table, values):
        insert = sqlite_insert if self.engine.dialect.name == 'sqlite' else pg_insert
        conn.execute(insert(table).values(**values).on_conflict_do_nothing())

    def _view(self, row, cached=False):
        value = dict(row)
        value['is_cached'] = cached
        value['cache_age'] = max(0, time.time() - value['collected_at']) if value['collected_at'] is not None else None
        return value

    def submit(self, video_id, options=None, refresh=False):
        video_id = str(video_id)
        is_search = bool(re.fullmatch(r'search:[0-9a-f]{32}',video_id)) and isinstance(options,dict) and options.get('kind')=='search'
        if not is_search and (not video_id.isdigit() or len(video_id) > 64):
            raise ValueError('video_id must be numeric and at most 64 digits')
        options = json.loads(json.dumps(options or {}, sort_keys=True, allow_nan=False))
        key = hashlib.sha256(json.dumps([video_id, options], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        now = time.time()
        with self.engine.begin() as conn:
            # Serialize all submissions for the video, including different options.
            lock_key = hashlib.sha256(video_id.encode()).hexdigest()
            self._insert_ignore(conn, keys, {'key': lock_key})
            conn.execute(update(keys).where(keys.c.key == lock_key).values(key=lock_key))
            paused = conn.execute(select(jobs).where(jobs.c.video_id == video_id, jobs.c.state.in_(['paused', 'interrupted'])).order_by(jobs.c.created_at.desc()).limit(1)).mappings().first()
            if paused:
                return self._view(paused)
            active = conn.execute(select(jobs).where(jobs.c.key == key, jobs.c.state.in_(['queued', 'running'])).order_by(jobs.c.created_at.desc()).limit(1)).mappings().first()
            if active:
                return self._view(active)
            if not refresh:
                cached = conn.execute(select(jobs).where(jobs.c.key == key, jobs.c.state.in_(['succeeded', 'partial']), jobs.c.collected_at >= now - self.cache_ttl_seconds).order_by(jobs.c.collected_at.desc()).limit(1)).mappings().first()
                if cached:
                    return self._view(cached, cached=True)
            value = dict(job_id=str(uuid.uuid4()), key=key, video_id=video_id, options=options, state='queued', created_at=now, updated_at=now, collected_at=None, pause_reason=None, result=None)
            conn.execute(jobs.insert().values(**value))
            return self._view(value)

    def get_job(self, job_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().first()
            return self._view(row) if row else None

    def list_jobs(self, limit=20):
        if not 1 <= limit <= 1000:
            raise ValueError('limit must be between 1 and 1000')
        with self.engine.connect() as conn:
            return [self._view(row) for row in conn.execute(select(jobs).order_by(jobs.c.created_at.desc()).limit(limit)).mappings()]

    def _source_lock(self, conn):
        self._insert_ignore(conn, keys, {'key': 'source:douyin'})
        conn.execute(update(keys).where(keys.c.key == 'source:douyin').values(key='source:douyin'))

    def claim_next(self):
        with self.engine.begin() as conn:
            self._source_lock(conn)
            if conn.execute(select(jobs.c.job_id).where(jobs.c.state == 'paused').limit(1)).first():
                return None
            candidate = select(jobs.c.job_id).where(jobs.c.state == 'queued').order_by(jobs.c.created_at).limit(1)
            if self.engine.dialect.name == 'postgresql':
                candidate = candidate.with_for_update(skip_locked=True)
            row = conn.execute(update(jobs).where(jobs.c.job_id == candidate.scalar_subquery(), jobs.c.state == 'queued').values(state='running', updated_at=time.time()).returning(*jobs.c)).mappings().first()
            return self._view(row) if row else None

    def finish(self, job_id, result, state='succeeded'):
        if state not in ('succeeded', 'partial', 'failed'):
            raise ValueError('Invalid completion state')
        # JSON round trip rejects bytes and mutable references before opening transaction.
        result = json.loads(json.dumps(result, allow_nan=False))
        now = time.time()
        with self.engine.begin() as conn:
            changed = conn.execute(update(jobs).where(jobs.c.job_id == job_id, jobs.c.state == 'running').values(state=state, result=result, collected_at=now, updated_at=now).returning(jobs.c.video_id)).first()
            if changed is None:
                raise ValueError('Only a running job can finish')
            for raw in result.get('raw_responses', []):
                self._validate_raw(raw)
                self._insert_ignore(conn, raw_responses, dict(job_id=job_id, sha256=raw['sha256'], path=raw['path'], size=raw['size']))
            conn.execute(snapshots.insert().values(job_id=job_id, video_id=changed[0], collected_at=now, metrics=result.get('metrics', {})))
        return self.get_job(job_id)

    def pause(self, job_id, reason, result=None):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Pause reason is required')
        if result is not None:
            result = json.loads(json.dumps(result, allow_nan=False))
        with self.engine.begin() as conn:
            self._source_lock(conn)
            values = dict(state='paused', pause_reason=reason, updated_at=time.time())
            if result is not None:
                values.update(result=result, collected_at=time.time())
            changed = conn.execute(update(jobs).where(jobs.c.job_id == job_id, jobs.c.state.in_(['queued', 'running'])).values(**values))
            if changed.rowcount != 1:
                raise ValueError('Only queued or running jobs can pause')
            if result is not None:
                for raw in result.get('raw_responses', []):
                    self._validate_raw(raw)
                    self._insert_ignore(conn, raw_responses, dict(job_id=job_id, sha256=raw['sha256'], path=raw['path'], size=raw['size']))
        return self.get_job(job_id)

    def resume(self, job_id, conditions_changed=False):
        with self.engine.begin() as conn:
            allowed = ['interrupted', 'paused'] if conditions_changed else ['interrupted']
            changed = conn.execute(update(jobs).where(jobs.c.job_id == job_id, jobs.c.state.in_(allowed)).values(state='queued', updated_at=time.time()))
            if changed.rowcount != 1:
                raise ValueError('Paused jobs require explicit conditions_changed=True; only interrupted/paused jobs can resume')
        return self.get_job(job_id)

    def recover_interrupted(self):
        """Call only at exclusive worker startup, never while another worker is active."""
        with self.engine.begin() as conn:
            return conn.execute(update(jobs).where(jobs.c.state == 'running').values(state='interrupted', updated_at=time.time())).rowcount

    def _validate_raw(self, raw):
        digest = raw.get('sha256', '')
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid raw hash')
        relative = Path('raw') / digest[:2] / (digest + '.bin')
        if raw.get('path') != relative.as_posix():
            raise ValueError('Invalid raw path')
        path = self.data_dir / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing raw evidence')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest or len(body) != raw.get('size'):
            raise ValueError('Raw evidence integrity mismatch')

    def save_raw(self, body: bytes):
        if not isinstance(body, bytes):
            raise TypeError('Raw body must be bytes')
        digest = hashlib.sha256(body).hexdigest()
        relative = Path('raw') / digest[:2] / (digest + '.bin')
        path = self.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = dict(sha256=digest, path=relative.as_posix(), size=len(body))
        fd, temp = tempfile.mkstemp(prefix='.raw-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(body); file.flush(); os.fsync(file.fileno())
            try:
                # Linking atomically publishes a complete file and never replaces evidence.
                os.link(temp, path)
            except FileExistsError:
                pass
            self._validate_raw(descriptor)
        finally:
            os.unlink(temp)
        return descriptor

