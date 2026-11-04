from datetime import timedelta
import json
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from test_api import setup, login, sample
from app.models import AnalysisJob, Topic, TopicDecision, now
from app.worker import run_once, recover_stale
from app.research_engine import grounded_topics, rule_clusters
from app import providers
from app.config import settings

def enqueue(client, **extra):
    return client.post('/analysis-jobs', json={'is_demo': True, **extra})

def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)

def test_grounded_end_to_end_and_decisions(setup):
    client, engine = setup
    assert client.get('/topics?is_demo=true').status_code == 401
    login(client)
    client.post('/imports', json=sample())
    job = enqueue(client).json()
    assert job['status'] == 'queued'
    assert enqueue(client).json()['id'] == job['id']
    assert run_once(factory(engine)) is True
    assert run_once(factory(engine)) is False
    result = client.get('/analysis-jobs/' + job['id']).json()
    assert result['status'] == 'succeeded' and result['result']['scope']['comments'] == 2
    topics = client.get('/topics?is_demo=true').json()['items']
    assert len(topics) == 3
    assert client.get('/topics?is_demo=false').json()['items'] == []
    for topic in topics:
        assert topic['evidence'] and topic['support_count'] == 1
        assert topic['evidence'][0]['source_url'] == 'https://example.com/demo/sky'
        assert '不能推断' in topic['uncertainty']
    selected = topics[0]['id']
    assert client.patch('/topics/' + selected, json={'status': 'approved', 'favorite': True, 'note': '保留动画方向'}).json()['status'] == 'approved'
    assert len(client.get('/topics/' + selected + '/decisions').json()['items']) == 1
    assert client.patch('/topics/' + selected, json={'favorite': None}).status_code == 422
    merged = client.post('/topics/' + topics[1]['id'] + '/merge', json={'target_id': selected}).json()
    assert merged['support_count'] == 2
    assert client.patch('/topics/' + topics[1]['id'], json={'status': 'candidate'}).status_code == 409
    assert client.post('/topics/' + selected + '/merge', json={'target_id': selected}).status_code == 422
    assert client.delete('/library?is_demo=true').status_code == 200
    assert client.get('/topics?is_demo=true').json()['items'] == []
    with factory(engine)() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisJob)) == 0
        assert db.scalar(select(func.count()).select_from(TopicDecision)) == 0

def test_duplicate_comments_do_not_inflate_support(setup):
    client, engine = setup
    login(client)
    payload = sample()
    video = payload['data']['videos'][0]
    video['comments'] = [{'external_id': f'c{i}', 'text': '为什么日落是红色？'} for i in range(6)]
    video['related_searches'] = []
    client.post('/imports', json=payload)
    enqueue(client)
    run_once(factory(engine))
    topic = client.get('/topics?is_demo=true').json()['items'][0]
    assert len(topic['evidence']) == 6
    assert topic['support_count'] == topic['coverage']['unique_comments'] == 1
    assert topic['scores']['demand']['value'] == 20

def test_inputs_and_unconfigured_model(setup):
    client, _ = setup
    login(client)
    assert enqueue(client).status_code == 422
    assert enqueue(client, engine='model').status_code == 422
    assert enqueue(client, weights={key: 0 for key in ('demand', 'evidence', 'explainability', 'freshness')}).status_code == 422

def test_stale_recovery_and_purge_protection(setup):
    client, engine = setup
    login(client)
    client.post('/imports', json=sample())
    job = enqueue(client).json()
    with factory(engine)() as db:
        obj = db.get(AnalysisJob, job['id'])
        obj.status, obj.started_at = 'running', now() - timedelta(hours=1)
        db.commit()
    assert client.delete('/library?is_demo=true').status_code == 409
    with factory(engine)() as db:
        recover_stale(db)
        assert db.get(AnalysisJob, job['id']).status == 'queued'
        obj = db.get(AnalysisJob, job['id'])
        obj.engine, obj.status = 'model', 'running'
        db.commit()
        recover_stale(db)
        assert db.get(AnalysisJob, job['id']).status == 'outcome_unknown'
    assert client.post('/analysis-jobs/' + job['id'] + '/retry').status_code == 409

def configure_model(monkeypatch):
    config = settings()
    for key, value in {'analysis_model': 'test-model', 'analysis_api_key': 'fake-not-a-real-key', 'analysis_base_url': 'https://model.example/v1',
                       'analysis_input_price_per_million': 1.0, 'analysis_output_price_per_million': 1.0}.items():
        monkeypatch.setattr(config, key, value)
    return config

def test_mock_model_grounding_usage_and_no_recharge(setup, monkeypatch):
    client, engine = setup
    login(client)
    configure_model(monkeypatch)
    client.post('/imports', json=sample())
    calls = []
    class Fake:
        def request(self, config, prompt, key):
            calls.append(prompt)
            record = json.loads(prompt)['records'][0]
            return {'text': json.dumps({'topics': [{'title': '日落的颜色', 'question': '日落为什么变红', 'category': '知识问题', 'evidence_ids': [record['id']]}]}), 'usage': {'input_tokens': 100, 'output_tokens': 20}}
    monkeypatch.setitem(providers.ADAPTERS, 'openai-compatible', Fake())
    job = enqueue(client, engine='model').json()
    run_once(factory(engine))
    result = client.get('/analysis-jobs/' + job['id']).json()
    assert result['status'] == 'succeeded'
    assert result['result']['estimated_cost'] == .00012
    assert enqueue(client, engine='model').json()['id'] == job['id']
    assert not run_once(factory(engine)) and len(calls) == 1
    assert client.post('/analysis-jobs/' + job['id'] + '/retry').status_code == 409

def test_model_invented_evidence_rejected_and_budget_guard(setup, monkeypatch):
    client, engine = setup
    login(client)
    config = configure_model(monkeypatch)
    client.post('/imports', json=sample())
    monkeypatch.setattr(config, 'analysis_budget_per_job', .000001)
    assert enqueue(client, engine='model').status_code == 422
    monkeypatch.setattr(config, 'analysis_budget_per_job', .25)
    class Fake:
        def request(self, *args):
            return {'text': json.dumps({'topics': [{'title': '捏造的主题', 'question': '不存在的证据', 'category': '知识问题', 'evidence_ids': ['invented']}]}), 'usage': {'input_tokens': 100, 'output_tokens': 20}}
    monkeypatch.setitem(providers.ADAPTERS, 'openai-compatible', Fake())
    job = enqueue(client, engine='model').json()
    run_once(factory(engine))
    assert client.get('/analysis-jobs/' + job['id']).json()['status'] == 'failed'
    assert client.get('/topics?is_demo=true').json()['items'] == []
    assert client.post('/analysis-jobs/' + job['id'] + '/retry').status_code == 409

def test_unknown_model_call_not_retried(setup, monkeypatch):
    client, engine = setup
    login(client)
    configure_model(monkeypatch)
    client.post('/imports', json=sample())
    class Fake:
        def request(self, *args):
            raise providers.OutcomeUnknown('模拟读取超时')
    monkeypatch.setitem(providers.ADAPTERS, 'openai-compatible', Fake())
    job = enqueue(client, engine='model').json()
    run_once(factory(engine))
    assert client.get('/analysis-jobs/' + job['id']).json()['status'] == 'outcome_unknown'
    assert client.post('/analysis-jobs/' + job['id'] + '/retry').status_code == 409
    assert not run_once(factory(engine))
