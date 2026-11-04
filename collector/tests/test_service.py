import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from dycollector.service import CollectorService
from unittest.mock import patch
import asyncio

class ServiceTests(unittest.TestCase):
    def test_restricted_malformed_payload_pauses_remaining_jobs(self):
        class FakeBrowser:
            def __init__(self,*args,**kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def collect(self,video_id,**kwargs):
                return {'video_id':video_id,'restriction':'HTTP 429','detail':{'aweme_id':video_id,'author':['invalid']},'responses':[]}
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            first=service.submit('7667409251216819441')
            second=service.submit('7697720115396094073')
            with patch('dycollector.service.GuestBrowser',FakeBrowser): asyncio.run(service.run_pending())
            self.assertEqual(service.store.get_job(first['job_id'])['state'],'paused')
            self.assertEqual(service.store.get_job(second['job_id'])['state'],'queued')
            service.store.engine.dispose()

    def test_result_text_budget(self):
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            job=service.submit('7667409251216819441'); service.store.claim_next()
            service.store.finish(job['job_id'],{'comments':{'items':[{'text':'x'*1000000}]}})
            result=service.result(job['job_id'],limit=1)
            self.assertLess(len(result['comments']['items'][0]['text']),2100)
            service.store.engine.dispose()
    def test_pause_reason_visible(self):
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            job=service.submit('7667409251216819441')
            service.store.pause(job['job_id'],'verification required')
            self.assertEqual(service.public_job(service.store.get_job(job['job_id']))['pause_reason'],'verification required')
            service.store.engine.dispose()
    def test_submit_rejects_arbitrary_url(self):
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            with self.assertRaises(ValueError): service.submit('http://127.0.0.1/')
            service.store.engine.dispose()

    def test_bounded_options(self):
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            with self.assertRaises(ValueError): service.submit('7667409251216819441',{'max_pages':100000})
            service.store.engine.dispose()

    def test_search_is_durable_and_deduplicated(self):
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            first=service.submit_search('科普',10,3)
            second=service.submit_search('科普',10,3)
            self.assertEqual(first['job_id'],second['job_id'])
            self.assertEqual(first['options']['kind'],'search')
            service.store.engine.dispose()

    def test_search_result_offset(self):
        with TemporaryDirectory() as folder:
            service=CollectorService('sqlite:///'+str(Path(folder)/'db.sqlite'),folder)
            job=service.submit_search('科普');service.store.claim_next()
            service.store.finish(job['job_id'],{'videos':[{'video_id':str(i)} for i in range(5)]})
            self.assertEqual(service.result(job['job_id'],2,2)['videos'],[{'video_id':'2'},{'video_id':'3'}])
            service.store.engine.dispose()
