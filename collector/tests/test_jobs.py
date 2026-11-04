import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import select, update
from dycollector.store import Store, jobs, raw_responses, snapshots

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.url = 'sqlite:///' + str(self.root / 'jobs.db')
        self.store = Store(self.url, self.root / 'data')
    def tearDown(self):
        self.store.engine.dispose()
        self.tmp.cleanup()
    def test_dedup_cache_options_expiry_refresh(self):
        a = self.store.submit('123', {'comments': True})
        self.assertEqual(a['job_id'], self.store.submit('123', {'comments': True})['job_id'])
        self.store.claim_next()
        self.store.finish(a['job_id'], {'metrics': {'likes': 1}})
        cached = self.store.submit('123', {'comments': True})
        self.assertTrue(cached['is_cached'])
        self.assertGreaterEqual(cached['cache_age'], 0)
        self.assertIsNotNone(cached['collected_at'])
        self.assertNotEqual(a['job_id'], self.store.submit('123', {'comments': False})['job_id'])
        refreshed = self.store.submit('123', {'comments': True}, refresh=True)
        self.assertNotEqual(a['job_id'], refreshed['job_id'])
        with self.store.engine.begin() as conn:
            conn.execute(update(jobs).where(jobs.c.job_id == a['job_id']).values(collected_at=0))
        self.store.claim_next()
        self.store.claim_next()
        self.store.finish(refreshed['job_id'], {'metrics': {'likes': 2}})
        with self.store.engine.begin() as conn:
            self.assertEqual(2, len(conn.execute(select(snapshots)).all()))
        self.assertEqual(3, len(self.store.list_jobs()))
    def test_expired_cache_creates_new_job(self):
        a = self.store.submit('123'); self.store.claim_next(); self.store.finish(a['job_id'], {})
        with self.store.engine.begin() as conn:
            conn.execute(update(jobs).values(collected_at=0))
        self.assertNotEqual(a['job_id'], self.store.submit('123')['job_id'])
    def test_pause_persists_and_refresh_does_not_bypass(self):
        a = self.store.submit('123'); self.store.claim_next()
        self.store.pause(a['job_id'], 'blocked_verification')
        reopened = Store(self.url, self.root / 'data')
        try:
            self.assertEqual(a['job_id'], reopened.submit('123', refresh=True)['job_id'])
            self.assertIsNone(reopened.claim_next())
            with self.assertRaises(ValueError): reopened.resume(a['job_id'])
            resumed = reopened.resume(a['job_id'], conditions_changed=True)
            self.assertEqual('blocked_verification', resumed['pause_reason'])
            self.assertEqual('queued', resumed['state'])
        finally: reopened.engine.dispose()
    def test_crash_requires_explicit_resume(self):
        a = self.store.submit('123'); self.store.claim_next()
        self.assertEqual(1, self.store.recover_interrupted())
        self.assertEqual('interrupted', self.store.get_job(a['job_id'])['state'])
        self.assertIsNone(self.store.claim_next())
        self.assertEqual('queued', self.store.resume(a['job_id'])['state'])
    def test_concurrent_submissions_share_one_active_job(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            submitted = list(pool.map(lambda _: self.store.submit('123'), range(18)))
        self.assertEqual(1, len({j['job_id'] for j in submitted}))
        self.assertEqual(1, len(self.store.list_jobs()))
    def test_atomic_multiworker_claim(self):
        for n in range(12): self.store.submit(str(n))
        def claim(_): return self.store.claim_next()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            claimed = list(pool.map(claim, range(18)))
        ids = [j['job_id'] for j in claimed if j]
        self.assertEqual(12, len(ids)); self.assertEqual(12, len(set(ids)))
    def test_raw_content_addressed_and_transaction_rollback(self):
        raw = self.store.save_raw(b'{"original":true}')
        self.assertEqual(raw, self.store.save_raw(b'{"original":true}'))
        a = self.store.submit('123'); self.store.claim_next()
        invalid = dict(raw, sha256='0' * 64)
        with self.assertRaises(ValueError):
            self.store.finish(a['job_id'], {'raw_responses': [raw, invalid]})
        self.assertEqual('running', self.store.get_job(a['job_id'])['state'])
        with self.store.engine.begin() as conn:
            self.assertEqual([], conn.execute(select(raw_responses)).all())
        self.store.finish(a['job_id'], {'raw_responses': [raw], 'metrics': {'likes': 4}})
        self.assertNotIn('original', str(self.store.get_job(a['job_id'])))
        self.assertTrue((self.root / 'data' / raw['path']).is_file())
    def test_source_pause_blocks_other_video_and_preserves_partial_evidence(self):
        a = self.store.submit('123'); self.store.claim_next()
        raw = self.store.save_raw(b'partial evidence')
        self.store.pause(a['job_id'], 'http_429', result={'raw_responses': [raw], 'metrics': {'likes': 1}})
        other = self.store.submit('456')
        self.assertIsNone(self.store.claim_next())
        self.assertEqual('queued', self.store.get_job(other['job_id'])['state'])
        self.assertEqual(1, self.store.get_job(a['job_id'])['result']['metrics']['likes'])
        with self.store.engine.begin() as conn:
            self.assertEqual(1, len(conn.execute(select(raw_responses)).all()))
        self.store.resume(a['job_id'], conditions_changed=True)
        self.assertIsNotNone(self.store.claim_next())
    def test_database_failure_rolls_back_job_raw_index_and_snapshot(self):
        from sqlalchemy import event
        raw = self.store.save_raw(b'evidence')
        a = self.store.submit('123'); self.store.claim_next()
        def fail_snapshot(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith('INSERT INTO collector_snapshots'):
                raise RuntimeError('simulated database failure')
        event.listen(self.store.engine, 'before_cursor_execute', fail_snapshot)
        try:
            with self.assertRaises(RuntimeError):
                self.store.finish(a['job_id'], {'raw_responses': [raw]})
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', fail_snapshot)
        self.assertEqual('running', self.store.get_job(a['job_id'])['state'])
        with self.store.engine.begin() as conn:
            self.assertEqual([], conn.execute(select(raw_responses)).all())
            self.assertEqual([], conn.execute(select(snapshots)).all())
    def test_existing_raw_corruption_never_overwritten(self):
        raw = self.store.save_raw(b'one')
        path = self.root / 'data' / raw['path']; path.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): self.store.save_raw(b'one')
        self.assertEqual(b'corrupt', path.read_bytes())

if __name__ == '__main__': unittest.main()


