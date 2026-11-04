import unittest
from dycollector.browser import parse_video_ref, classify_gate, download_allowed

class BrowserPolicyTests(unittest.TestCase):
    def test_url_allowlist(self):
        self.assertEqual(parse_video_ref('https://www.douyin.com/video/7667409251216819441'), '7667409251216819441')
        for url in ['http://127.0.0.1/video/7667409251216819441', 'https://www.douyin.com.evil.com/video/7667409251216819441', 'https://x@www.douyin.com/video/7667409251216819441', 'https://www.douyin.com:444/video/7667409251216819441']:
            with self.assertRaises(ValueError): parse_video_ref(url)

    def test_function_gates_not_promotion(self):
        self.assertEqual(classify_gate('登录后免费畅享高清视频'), {})
        self.assertEqual(classify_gate('登录后可查看更多评论'), {'comments':'blocked_login'})
        self.assertEqual(classify_gate('登录后展开更多'), {'replies':'blocked_login'})
        self.assertEqual(classify_gate('请完成下列验证'), {'source':'blocked_verification'})

    def test_conflicting_download_flags(self):
        self.assertFalse(download_allowed({'video_control': {'allow_download': True, 'download_info': {'fail_info': {'reason':'risk_info'}, 'level':2}}}))
        self.assertFalse(download_allowed({}))
        self.assertTrue(download_allowed({'video_control': {'allow_download':True,'download_info':{'level':0}}}))
