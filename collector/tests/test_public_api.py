import asyncio
import hashlib
import json
import unittest
from types import SimpleNamespace

from dycollector.public_api import PublicAPI
from dycollector.normalize import normalize_capture

VIDEO = '7667409251216819441'


class Store:
    def save_raw(self, body):
        return {'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body), 'path': 'raw/test.bin'}


class Response:
    def __init__(self, payload, status=200):
        self.status, self.disposed = status, False
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    async def body(self): return self.payload
    async def dispose(self): self.disposed = True


class Request:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def detail():
    return Response({'status_code': 0, 'aweme_detail': {'aweme_id': VIDEO,
        'suggest_words': {'suggest_words': [{'scene': 'feed_bottom_rec', 'words': [{'word': 'real term'}]}]}}})


def comment(cid='c', parent='0', video=VIDEO, replies=0):
    return {'cid': cid, 'reply_id': parent, 'aweme_id': video, 'text': 'source text', 'reply_comment_total': replies}


class PublicAPITests(unittest.TestCase):
    def run_collect(self, responses, **kwargs):
        req = Request(responses)
        row = asyncio.run(PublicAPI(Store(), SimpleNamespace(request=req)).collect(VIDEO, **kwargs))
        return row, req

    def test_collect_preserves_evidence_and_scene_and_exact_attribution(self):
        row, req = self.run_collect([detail(), Response({'status_code': 0, 'comments': [comment(replies=1)], 'total': 1, 'has_more': 0, 'cursor': 20}),
                                    Response({'status_code': 0, 'comments': [comment('r', 'c')], 'total': 1, 'has_more': 0, 'cursor': 20})])
        result = normalize_capture(row)
        self.assertEqual(result['comments']['unique_count'], 1)
        self.assertEqual(result['replies']['items'][0]['parent_cid'], 'c')
        self.assertEqual(result['recommendations']['feed_bottom_rec']['words'], ['real term'])
        self.assertEqual(len(row['responses']), 3)
        self.assertTrue(all(x['sha256'] for x in row['responses']))
        self.assertTrue(row['reply_sampling'])
        for url, options in req.calls:
            self.assertTrue(url.startswith('https://so.douyin.com/aweme/v1/web/'))
            self.assertEqual(options['max_retries'], 0)
            self.assertEqual(options['max_redirects'], 0)
            self.assertNotIn('Cookie', options['headers'])

    def test_http_restriction_stops_all_further_requests_even_json(self):
        blocked = Response({'status_code': 0}, 403)
        row, req = self.run_collect([blocked])
        self.assertEqual(row['restriction'], 'HTTP 403')
        self.assertEqual(len(req.calls), 1)
        self.assertTrue(blocked.disposed)
        self.assertEqual(row['comment_pages'], [])

    def test_nonzero_platform_code_stops_reply_and_later_pages(self):
        row, req = self.run_collect([detail(), Response({'status_code': 10000, 'comments': []})])
        self.assertIn('restriction', row)
        self.assertEqual(len(req.calls), 2)

    def test_body_or_cleanup_failure_cannot_erase_http_restriction(self):
        class Broken(Response):
            async def body(self): raise OSError('private transport details')
            async def dispose(self): raise OSError('private cleanup details')
        row, req = self.run_collect([Broken({}, 429)])
        self.assertEqual(row['restriction'], 'HTTP 429')
        self.assertEqual(len(req.calls), 1)
        self.assertNotIn('private', json.dumps(row))

    def test_limit_keeps_original_more_and_explicit_truncation(self):
        row, req = self.run_collect([detail(), Response({'status_code': 0, 'comments': [comment('a'), comment('b')], 'total': 2, 'has_more': 0, 'cursor': 20})], max_comments=1)
        page = row['comment_pages'][0]
        self.assertEqual(len(page['comments']), 1)
        self.assertEqual(page['has_more'], 0)
        self.assertTrue(page['truncated'])
        self.assertTrue(row['comment_limit_reached'])
        self.assertEqual(req.calls[1][1]['params']['count'], 1)

    def test_conflicting_video_is_left_for_normalizer_rejection(self):
        row, req = self.run_collect([detail(), Response({'comments': [comment(video='7697720115396094073')], 'has_more': 0})])
        result = normalize_capture(row)
        self.assertEqual(result['comments']['unique_count'], 0)
        self.assertEqual(result['comments']['status'], 'partial')

    def test_invalid_detail_does_not_collect_comments(self):
        row, req = self.run_collect([Response({'aweme_detail': {'aweme_id': '7697720115396094073'}})])
        self.assertEqual(row['detail_status'], 'rejected_attribution')
        self.assertEqual(len(req.calls), 1)

    def test_empty_page_stops_without_retry(self):
        row, req = self.run_collect([detail(), Response({'comments': [], 'has_more': 1, 'cursor': 20})])
        self.assertEqual(row['comment_pagination_stop'], 'empty_page')
        self.assertEqual(len(req.calls), 2)

    def test_non_json_verification_stops_all_requests(self):
        row, req = self.run_collect([Response('安全验证'.encode())])
        self.assertIn('restriction', row)
        self.assertEqual(len(req.calls), 1)


if __name__ == '__main__': unittest.main()
