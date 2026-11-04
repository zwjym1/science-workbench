import copy
import json
import unittest
from pathlib import Path
import subprocess
import sys
import tempfile
from dycollector.normalize import normalize_capture


def comment(cid='c', video='123', parent='0'):
    return {'cid': cid, 'aweme_id': video, 'reply_id': parent, 'text': 'hello'}


def page(items, video='123', parent=None, **kw):
    refs = {'item_id' if parent else 'aweme_id': [video]}
    if parent:
        refs['comment_id'] = [parent]
    return {'references': refs, 'comments': items, 'has_more': 0, **kw}


class NormalizeTests(unittest.TestCase):
    def test_wrong_video_is_rejected_even_when_target_flag_true(self):
        row = {'video_id': '123', 'detail': {'aweme_id': '456'}, 'comment_pages': [page([comment()], video='456', target_identified=True)]}
        result = normalize_capture(row)
        self.assertEqual(result['detail']['status'], 'missing')
        self.assertEqual(result['comments']['items'], [])
        self.assertTrue(result['rejections'])

    def test_duplicate_and_reply_parent_validation(self):
        row = {'video_id': '123', 'comment_pages': [page([comment(), comment(), comment('bad','456')])],
               'reply_pages': [page([comment('r', parent='c'), comment('wrong', parent='other'), comment('video','456','c')], parent='c'),
                               page([comment('unseen', parent='unknown')], parent='unknown')]}
        out = normalize_capture(row)
        self.assertEqual([c['cid'] for c in out['comments']['items']], ['c'])
        self.assertEqual([c['cid'] for c in out['replies']['items']], ['r'])
        self.assertEqual(out['replies']['items'][0]['parent_cid'], 'c')

    def test_embedded_replies_are_deduplicated_and_checked(self):
        c = comment()
        c['reply_comment'] = [comment('r', parent='c'), comment('x', parent='bad')]
        out = normalize_capture({'video_id':'123', 'comment_pages':[page([c])], 'reply_pages':[page([comment('r',parent='c')],parent='c')]})
        self.assertEqual(out['replies']['unique_count'], 1)

    def test_missing_empty_and_has_more_remain_distinct(self):
        self.assertEqual(normalize_capture({'video_id':'123'})['comments']['status'], 'missing')
        for items, more, expected in [([], 0, 'observed_empty'), ([], 1, 'partial'), ([comment()], 1, 'partial'), ([comment()], 0, 'available')]:
            with self.subTest(expected=expected, items=items):
                out = normalize_capture({'video_id':'123', 'comment_pages':[page(items,has_more=more)]})
                self.assertEqual(out['comments']['status'],expected)
        self.assertEqual(normalize_capture({'video_id':'123','comment_pages':[{'references':{'aweme_id':['123']}}]})['comments']['status'],'missing')

    def test_gate_preserves_observed_items(self):
        out = normalize_capture({'video_id':'123','comment_gate':True,'comment_pages':[page([comment()],has_more=1)]})
        self.assertEqual(out['comments']['status'],'blocked_login')
        self.assertEqual(out['comments']['unique_count'],1)

    def test_multiple_scenes_and_null_words(self):
        row = {'video_id':'123','detail':{'aweme_id':'123'}, 'nested_suggest_words':[{'json_path':'$.suggest_words','value':{'suggest_words':[
            {'scene':'comment_top_rec','words':None}, {'scene':'detail_inbox_rex','words':[{'word':'one'}, {'word':'one'}]}, {'scene':'other'}]}}]}
        out = normalize_capture(row)['recommendations']
        self.assertEqual(out['comment_top_rec']['status'],'observed_empty')
        self.assertEqual(out['detail_inbox_rex']['words'],['one'])
        self.assertEqual(out['other']['status'],'missing')

    def test_unattributed_independent_words_not_video_recommendations(self):
        row = {'video_id':'123','independent_suggest_words':[{'references':{'from_group_id':['456']},'payload':{'data':[{'type':'inbox','words':[{'word':'bad'}]}]}}]}
        out = normalize_capture(row)
        self.assertEqual(out['recommendations'],{})
        self.assertEqual(out['independent_suggest_words'],[])

    def test_safe_allowlist_and_input_unchanged(self):
        row = {'video_id':'123','Cookie':'SECRET','detail':{'aweme_id':'123','desc':'caption','authentication_token':'SECRET','video':{'play_addr':{'url_list':['https://cdn/?x-signature=SECRET']}}},'responses':[{'path':'https://host/?cookie=SECRET','headers':{'Cookie':'SECRET'}}]}
        before = copy.deepcopy(row)
        encoded = json.dumps(normalize_capture(row))
        self.assertNotIn('SECRET',encoded)
        self.assertNotIn('url_list',encoded)
        self.assertEqual(row,before)

class RejectedCompletenessTests(unittest.TestCase):
    def test_rejected_items_cannot_claim_observed_empty_or_complete(self):
        out = normalize_capture({'video_id':'123','comment_pages':[page([comment(video='456')])]})
        self.assertEqual(out['comments']['status'],'partial')
        self.assertEqual(out['comments']['stop_reason'],'rejected_attribution')

    def test_cursor_is_numeric_metadata_not_arbitrary_raw_text(self):
        out = normalize_capture({'video_id':'123','comment_pages':[page([],cursor='https://cdn/?x-signature=SECRET')]})
        self.assertNotIn('SECRET',json.dumps(out))


class ReplayTests(unittest.TestCase):
    """Replay runs on a synthetic batch, not on the private evidence dir.

    The real batch summaries are deliberately not published, so the test builds
    its own capture-shaped batch and asserts the invariants that matter: the
    replay flag, totals recomputed from normalized rows, provenance carrying the
    batch timestamp, the source file staying byte-identical, and a second write
    to the same artifact refusing to overwrite.
    """

    def _batch(self, folder):
        rows = []
        for index in range(3):
            video = f'10{index}'
            rows.append({
                'video_id': video,
                'detail': {'aweme_id': video, 'desc': f'row {index}'},
                'comment_pages': [page([comment(f'c{index}-1', video),
                                        comment(f'c{index}-2', video)], video=video)],
                'reply_pages': [page([comment(f'r{index}', video=video, parent=f'c{index}-1')],
                                     video=video, parent=f'c{index}-1')],
            })
        source = folder / 'batch.json'
        source.write_text(json.dumps({'ended_at': '2026-10-20T09:00:00+00:00', 'rows': rows}),
                          encoding='utf-8')
        return source

    def test_historical_replay_has_origin_and_preserves_evidence(self):
        replay = Path(__file__).resolve().parents[1] / 'replay.py'
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = self._batch(folder)
            before = source.read_bytes()
            output = folder / 'report.json'
            result = subprocess.run([sys.executable, str(replay), '--source', str(source),
                                     '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertIs(report['replay'], True)
            self.assertEqual(report['totals']['videos'], 3)
            self.assertEqual(report['totals']['unique_top_level_comments'], 6)
            self.assertEqual(report['totals']['unique_replies'], 3)
            self.assertEqual(report['source_collected_at'], '2026-10-20T09:00:00+00:00')
            for row in report['rows']:
                self.assertIs(row['replay'], True)
                self.assertEqual(row['provenance']['source_batch_ended_at'],
                                 '2026-10-20T09:00:00+00:00')
                roots = {c['cid'] for c in row['comments']['items']}
                self.assertTrue(all(r['parent_cid'] in roots
                                    and r['video_id'] == row['video_id']
                                    for r in row['replies']['items']))
            again = subprocess.run([sys.executable, str(replay), '--source', str(source),
                                    '--output', str(output)], capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(source.read_bytes(), before)



    def test_truncated_final_page_is_partial(self):
        out=normalize_capture({'video_id':'123','comment_pages':[page([comment()],truncated=True,total=2)]})
        self.assertEqual(out['comments']['status'],'partial')
        self.assertEqual(out['comments']['stop_reason'],'limit_reached')

    def test_reply_totals_are_selected_parent_totals(self):
        out=normalize_capture({'video_id':'123','comment_pages':[page([comment('a'),comment('b')])],
            'reply_pages':[page([comment('r1',parent='a')],parent='a',total=3),page([comment('r2',parent='b')],parent='b',total=4)],'reply_sampling':True})
        self.assertEqual(out['replies']['platform_total'],7)
        self.assertEqual(out['replies']['status'],'partial')
        self.assertEqual(out['reply_scope']['parent_totals'],{'a':3,'b':4})

if __name__ == '__main__':
    unittest.main()
