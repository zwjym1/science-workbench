import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dycollector.content import extract_content


URL = 'https://v1.douyinvod.com/video?signature=SECRET'
DETAIL = {'video_control': {'allow_download': True, 'download_info': {'level': 0}},
          'video': {'download_addr': {'url_list': [URL, 'https://v2.douyinvod.com/backup']}}}


class Response:
    def __init__(self, status=200, body=b'video', headers=None):
        self.status, self.data = status, body
        self.headers = headers or {'content-type': 'video/mp4'}
    async def body(self):
        return self.data
    async def dispose(self):
        pass


class Request:
    def __init__(self, response):
        self.response, self.calls = response, []
    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ContentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.dns = patch('dycollector.content.socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('8.8.8.8', 443))])
        self.dns.start()
    async def asyncTearDown(self):
        self.dns.stop()
        self.tmp.cleanup()
    async def collect(self, detail=None, response=None, options=None):
        request = Request(response or Response())
        result = await extract_content(detail or copy.deepcopy(DETAIL), SimpleNamespace(request=request),
                                       self.out, options or {})
        return result, request
    async def test_default_never_downloads_or_invents_transcript(self):
        result, request = await self.collect()
        self.assertEqual(request.calls, [])
        self.assertEqual(result['media']['status'], 'not_requested')
        self.assertEqual(result['asr']['status'], 'not_requested')
        self.assertNotIn('text', json.dumps(result))
    async def test_forbidden_and_risk_flags_prevent_request(self):
        for control in ({'allow_download': False}, {'allow_download': True, 'download_info': {'level': 1}},
                        {'allow_download': True, 'download_info': {'fail_info': {'reason': 'forbidden'}}}):
            detail = copy.deepcopy(DETAIL)
            detail['video_control'] = control
            result, request = await self.collect(detail, options={'media': True})
            self.assertEqual(request.calls, [])
            self.assertEqual(result['media']['status'], 'blocked')
    async def test_redirect_and_403_do_not_retry(self):
        for status in (302, 403, 429):
            result, request = await self.collect(response=Response(status), options={'media': True})
            self.assertEqual(result['media']['status'], 'blocked')
            self.assertEqual(len(request.calls), 1)
            self.assertEqual(request.calls[0][1]['max_redirects'], 0)
            self.assertEqual(request.calls[0][1]['max_retries'], 0)
    async def test_download_budget(self):
        result, _ = await self.collect(response=Response(headers={'content-length': '150000001'}),
                                       options={'media': True})
        self.assertEqual(result['media']['reason'], 'size_limit')
        self.assertFalse(list(self.out.glob('*.mp4')))
    async def test_html_login_page_is_not_saved_as_media(self):
        result, _ = await self.collect(response=Response(body=b'<html>login</html>',
                                       headers={'content-type': 'text/html'}), options={'media': True})
        self.assertEqual(result['media']['reason'], 'unexpected_content_type')
        self.assertFalse(list(self.out.glob('*.mp4')))
    async def test_url_allowlist_and_private_addresses(self):
        for url in ('https://127.0.0.1/video', 'https://evil.example/video',
                    'https://douyinvod.com.evil.example/video', 'http://v1.douyinvod.com/video'):
            detail = copy.deepcopy(DETAIL)
            detail['video']['download_addr']['url_list'][0] = url
            result, request = await self.collect(detail, options={'media': True})
            self.assertEqual(result['media']['status'], 'blocked')
            self.assertEqual(request.calls, [])
        with patch('dycollector.content.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('10.0.0.1', 443))]):
            result, request = await self.collect(options={'media': True})
            self.assertEqual(request.calls, [])
    async def test_metadata_only_and_no_secret_url_on_exception(self):
        result, _ = await self.collect(options={'media': True})
        self.assertEqual(result['media']['bytes'], 5)
        self.assertNotIn('text', result['media'])
        self.assertNotIn('SECRET', json.dumps(result))
        result, _ = await self.collect(response=RuntimeError(URL + ' Cookie=SECRET'), options={'media': True})
        self.assertNotIn('SECRET', json.dumps(result))
    async def test_original_subtitles_first_with_provenance(self):
        detail = copy.deepcopy(DETAIL)
        detail['video']['subtitle_infos'] = [{'url': 'https://v1.douyinvod.com/subtitle'}]
        body = b'1\n00:00:01,000 --> 00:00:03,500\nhello\n'
        result, request = await self.collect(detail, Response(body=body))
        self.assertEqual(result['subtitles']['segments'][0]['text'], 'hello')
        self.assertEqual(result['subtitles']['segments'][0]['start'], 1.0)
        self.assertIn('source_path', result['subtitles'])
        self.assertEqual(len(request.calls), 1)
    async def test_no_audio_needs_review_and_no_arbitrary_ocr_command(self):
        with patch('dycollector.content._probe', return_value={'has_audio': False, 'duration_seconds': 5}):
            result, _ = await self.collect(options={'media': True, 'asr': True,
                                                   'ocr': True, 'ocr_command': 'evil'})
        self.assertEqual(result['asr']['status'], 'needs_review')
        self.assertEqual(result['asr']['reason'], 'no_audio')
        self.assertEqual(result['ocr']['status'], 'unavailable')
    async def test_actual_body_limit_without_content_length(self):
        with patch('dycollector.content.MAX_MEDIA_BYTES', 4):
            result, request = await self.collect(response=Response(body=b'12345'), options={'media': True})
        self.assertEqual(result['media']['reason'], 'size_limit')
        self.assertEqual(len(request.calls), 1)
        self.assertFalse(list(self.out.glob('*.mp4')))
    async def test_untrusted_subtitle_url_is_not_requested(self):
        detail = copy.deepcopy(DETAIL)
        detail['subtitle_infos'] = [{'url': 'https://127.0.0.1/subtitle'}]
        result, request = await self.collect(detail)
        self.assertEqual(result['subtitles']['status'], 'blocked')
        self.assertEqual(request.calls, [])
    async def test_playback_only_does_not_fallback_to_playback_download(self):
        detail = copy.deepcopy(DETAIL)
        detail['video']['play_addr'] = detail['video'].pop('download_addr')
        result, request = await self.collect(detail, options={'media': True})
        self.assertEqual(result['media']['status'], 'missing')
        self.assertEqual(request.calls, [])
    async def test_caption_sticker_and_creator_caption_paths(self):
        for field in ('sticker', 'creator'):
            detail = copy.deepcopy(DETAIL)
            url = 'https://static.douyin.com/cap.json'
            if field == 'sticker':
                detail['interaction_stickers'] = [{'auto_video_caption_info': {
                    'auto_captions': [{'url': {'url_list': [url]}}]}}]
                expected = 'interaction_stickers[0].auto_video_caption_info.auto_captions[0]'
            else:
                detail['video']['cla_info'] = {'caption_infos': [{'url': url}]}
                expected = 'video.cla_info.caption_infos[0]'
            result, request = await self.collect(detail, Response(body=json.dumps({
                'utterances': [{'start_time': 1000, 'end_time': 2000, 'text': 'hello'}]}).encode()))
            self.assertEqual(result['subtitles']['segments'][0]['start'], 1)
            self.assertEqual(result['subtitles']['source_path'], expected)
            self.assertEqual(len(request.calls), 1)
    async def test_invalid_declared_size_is_reported(self):
        detail = copy.deepcopy(DETAIL)
        detail['video']['download_addr']['data_size'] = 'invalid'
        result, request = await self.collect(detail, options={'media': True})
        self.assertEqual(result['media']['reason'], 'invalid_size')
        self.assertEqual(request.calls, [])
    async def test_asr_low_coverage_keeps_segments_and_review_label(self):
        def transcribe(argv, **kwargs):
            self.assertFalse(kwargs['shell'])
            folder = Path(argv[argv.index('--output-dir') + 1])
            folder.mkdir()
            (folder / 'transcript.json').write_text(json.dumps({
                'media_duration_seconds': 100,
                'segments': [{'start': 0, 'end': 1, 'text': 'hello'}]}))
        with patch('dycollector.content._probe', return_value={'has_audio': True}), \
                patch('dycollector.content.subprocess.run', side_effect=transcribe):
            result, _ = await self.collect(options={'media': True, 'asr': True})
        self.assertEqual(result['asr']['status'], 'needs_review')
        self.assertEqual(result['asr']['reason'], 'low_coverage')
        self.assertEqual(result['asr']['segments'][0]['text'], 'hello')


if __name__ == '__main__':
    unittest.main()

