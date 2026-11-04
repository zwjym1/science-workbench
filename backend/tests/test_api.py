import os
import json
from pathlib import Path
import pytest

os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['ADMIN_PASSWORD'] = 'test-password-123456'
os.environ['SESSION_SECRET'] = 'test-secret-123456789012345678901234567890'
os.environ['COOKIE_SECURE'] = 'false'

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from app.db import Base, get_db
from app.main import app
from app.models import ImportJob, Video, Comment, MetricSnapshot
from app.auth import attempts

@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def override():
        with Session(engine, expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_db] = override
    attempts.clear()
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()

def login(client):
    assert client.post('/auth/login', json={'password': os.environ['ADMIN_PASSWORD']}).status_code == 200

def sample():
    return json.loads((Path(__file__).parents[2] / 'samples/demo-import.json').read_text(encoding='utf-8'))

def test_auth_and_rate_limit(setup):
    client, _ = setup
    assert client.get('/videos').status_code == 401
    for _ in range(5):
        assert client.post('/auth/login', json={'password': 'bad'}).status_code == 401
    assert client.post('/auth/login', json={'password': 'bad'}).status_code == 429

def test_import_idempotency_detail_and_deletion(setup):
    client, engine = setup
    login(client)
    payload = sample()
    first = client.post('/imports', json=payload).json()
    assert first['status'] == 'succeeded'
    assert first['result']['comments_created'] == 2
    assert client.post('/imports', json=payload).json()['id'] == first['id']
    items = client.get('/videos', params={'q': '天空', 'is_demo': True}).json()['items']
    assert len(items) == 1 and items[0]['comments_count'] == 2
    detail = client.get('/videos/' + items[0]['id']).json()
    assert detail['snapshots'][0]['metrics']['views'] is None
    assert len(detail['comments']) == 2
    assert client.post('/imports/' + first['id'] + '/retry').json()['status'] == 'succeeded'
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MetricSnapshot)) == 1
        assert db.get(ImportJob, first['id']).raw_data == payload['data']
    assert client.delete('/library?is_demo=true').status_code == 200
    assert client.get('/videos').json()['total'] == 0
    assert client.get('/imports').json()['items'] == []

def test_new_snapshot_and_comment_dedupe(setup):
    client, engine = setup
    login(client)
    payload = sample()
    client.post('/imports', json=payload)
    payload['data']['videos'][0]['collected_at'] = '2026-10-21T08:00:00+08:00'
    payload['data']['videos'][0]['metrics']['likes'] = 3
    assert client.post('/imports', json=payload).json()['result']['videos_created'] == 0
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Video)) == 1
        assert db.scalar(select(func.count()).select_from(Comment)) == 2
        assert db.scalar(select(func.count()).select_from(MetricSnapshot)) == 2

def test_validation_and_demo_isolation(setup):
    client, _ = setup
    login(client)
    payload = sample()
    client.post('/imports', json=payload)
    payload['is_demo'] = False
    assert client.post('/imports', json=payload).status_code == 200
    assert client.get('/videos').json()['total'] == 2
    payload['data']['videos'][0]['collected_at'] = '2026-10-20T08:00:00'
    assert client.post('/imports', json=payload).status_code == 422
    client.post('/auth/logout')
    assert client.get('/videos').status_code == 401

def test_atomic_failure_and_retry(setup, monkeypatch):
    client, engine = setup
    login(client)
    import app.main as main
    actual = main.process_import
    def fail(db, job):
        actual(db, job)
        raise RuntimeError('simulated failure')
    monkeypatch.setattr(main, 'process_import', fail)
    result = client.post('/imports', json=sample()).json()
    assert result['status'] == 'failed'
    assert client.get('/videos').json()['total'] == 0
    monkeypatch.setattr(main, 'process_import', actual)
    assert client.post('/imports/' + result['id'] + '/retry').json()['status'] == 'succeeded'
    assert client.get('/videos').json()['total'] == 1

def test_invalid_session_and_metrics(setup):
    client, _ = setup
    client.cookies.set('session', 'malformed-token')
    assert client.get('/videos').status_code == 401
    client.cookies.clear()
    login(client)
    payload = sample()
    payload['data']['videos'][0]['metrics']['views'] = -1
    assert client.post('/imports', json=payload).status_code == 422
    payload = sample()
    payload['data']['videos'][0]['unexpected_field'] = 'must not silently discard'
    assert client.post('/imports', json=payload).status_code == 422

def test_partial_update_preserves_content_and_updates_comment(setup):
    client, _ = setup
    login(client)
    payload = sample()
    client.post('/imports', json=payload)
    video = payload['data']['videos'][0]
    expected = video.pop('content')
    video.pop('tags')
    video.pop('related_searches')
    video['collected_at'] = '2026-10-22T00:00:00Z'
    video['comments'][0]['text'] = '修正后的模拟评论'
    video['comments'][0]['likes'] = 5
    assert client.post('/imports', json=payload).json()['status'] == 'succeeded'
    video_id = client.get('/videos').json()['items'][0]['id']
    detail = client.get('/videos/' + video_id).json()
    assert detail['video']['content'] == expected
    assert detail['video']['tags'] == ['模拟数据', '光学']
    comment = next(c for c in detail['comments'] if c['text'] == '修正后的模拟评论')
    assert comment['likes'] == 5

def test_explicit_clear_and_older_snapshot(setup):
    client, _ = setup
    login(client)
    payload = sample()
    client.post('/imports', json=payload)
    update = sample()
    video = update['data']['videos'][0]
    video['collected_at'] = '2026-10-23T08:00:00+08:00'
    video.pop('content')
    first = client.post('/imports', json=update).json()
    video['content'] = None
    second = client.post('/imports', json=update).json()
    assert first['id'] != second['id']
    older = sample()
    older['data']['videos'][0]['title'] = '不应覆盖的新旧冲突'
    client.post('/imports', json=older)
    video_id = client.get('/videos').json()['items'][0]['id']
    detail = client.get('/videos/' + video_id).json()
    assert detail['video']['content'] is None
    assert detail['video']['title'] == video['title']
    assert detail['video']['collected_at'].startswith('2026-10-23T00:00:00')
