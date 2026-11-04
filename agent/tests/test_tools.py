import json
import tempfile
import unittest
import wave
from pathlib import Path

from clipagent.tools import (ArtifactStore, ToolContext, ToolError, build_tools,
                             make_storyboard, render_and_check, search_assets,
                             synthesize_tts, write_script)


def tool(name):
    return {t.name: t for t in build_tools()}[name]


class SearchAssetsTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ToolContext(Path(tempfile.mkdtemp()))

    def test_empty_query_is_rejected(self):
        with self.assertRaises(ToolError):
            search_assets({'query': '   '}, self.ctx)

    def test_limit_is_bounded(self):
        with self.assertRaises(ToolError):
            search_assets({'query': 'water', 'limit': 0}, self.ctx)
        with self.assertRaises(ToolError):
            search_assets({'query': 'water', 'limit': 21}, self.ctx)

    def test_every_hit_carries_licence_and_provenance(self):
        out = search_assets({'query': 'water', 'limit': 5}, self.ctx)
        self.assertEqual(out['status'], 'ok')
        self.assertTrue(out['assets'])
        for asset in out['assets']:
            self.assertIn('license', asset)
            self.assertIn('provenance', asset)

    def test_index_file_overrides_bundled_catalogue(self):
        index = self.ctx.workdir / 'index.json'
        index.write_text(json.dumps([
            {'id': 'z1', 'title': 'glacier melt', 'kind': 'video',
             'license': 'CC BY 4.0', 'provenance': 'fixture'}]),
            encoding='utf-8')
        ctx = ToolContext(self.ctx.workdir, assets=index)
        out = search_assets({'query': 'glacier'}, ctx)
        self.assertEqual([a['id'] for a in out['assets']], ['z1'])
        self.assertEqual(out['source'], str(index))


class WriteScriptTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ToolContext(Path(tempfile.mkdtemp()))

    def test_citations_are_mandatory(self):
        with self.assertRaises(ToolError):
            write_script({'topic': '水循环', 'citations': []}, self.ctx)

    def test_duration_is_bounded(self):
        with self.assertRaises(ToolError):
            write_script({'topic': 'x', 'duration_s': 5, 'citations': ['s']}, self.ctx)

    def test_every_sentence_cites_a_source(self):
        out = write_script({'topic': '水循环', 'duration_s': 60,
                            'citations': ['IPCC', 'USGS']}, self.ctx)
        self.assertEqual(out['citation_count'], 2)
        for sentence in out['sentences']:
            self.assertTrue(sentence['citation'])
            self.assertIn(sentence['citation'], ('IPCC', 'USGS'))


class StoryboardTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ToolContext(Path(tempfile.mkdtemp()))

    def test_shot_seconds_sum_to_declared_duration(self):
        sentences = [{'text': f's{i}', 'citation': 'c'} for i in range(3)]
        out = make_storyboard({'sentences': sentences, 'shots': 5,
                               'duration_s': 30}, self.ctx)
        self.assertAlmostEqual(sum(s['seconds'] for s in out['shots']), 30, places=2)
        self.assertEqual(len(out['shots']), 5)

    def test_shots_cycle_through_sentences_and_assets(self):
        sentences = [{'text': 'a', 'citation': 'c1'}, {'text': 'b', 'citation': 'c2'}]
        out = make_storyboard({'sentences': sentences, 'shots': 4,
                               'asset_ids': ['x', 'y'], 'duration_s': 8}, self.ctx)
        self.assertEqual([s['text'] for s in out['shots']], ['a', 'b', 'a', 'b'])
        self.assertEqual([s['asset_id'] for s in out['shots']], ['x', 'y', 'x', 'y'])

    def test_empty_sentences_is_rejected(self):
        with self.assertRaises(ToolError):
            make_storyboard({'sentences': [], 'shots': 3}, self.ctx)


class TtsTests(unittest.TestCase):
    def test_placeholder_track_matches_storyboard_duration(self):
        ctx = ToolContext(Path(tempfile.mkdtemp()))
        shots = [{'index': 0, 'seconds': 1.5}, {'index': 1, 'seconds': 2.5}]
        out = synthesize_tts({'shots': shots}, ctx)
        self.assertEqual(out['status'], 'unavailable')
        self.assertEqual(out['reason'], 'no_speech_engine_configured')
        with wave.open(out['audio_path']) as handle:
            seconds = handle.getnframes() / handle.getframerate()
        self.assertAlmostEqual(seconds, 4.0, places=2)

    def test_zero_duration_is_rejected(self):
        with self.assertRaises(ToolError):
            synthesize_tts({'shots': [{'index': 0, 'seconds': 0}]},
                           ToolContext(Path(tempfile.mkdtemp())))


class RenderTests(unittest.TestCase):
    def test_render_reports_truthful_checks(self):
        ctx = ToolContext(Path(tempfile.mkdtemp()), width=160, height=90, fps=6)
        if not ctx.ffmpeg:
            self.skipTest('ffmpeg not installed')
        shots = [{'index': i, 'seconds': 1.0} for i in range(3)]
        out = render_and_check({'shots': shots}, ctx)
        self.assertEqual(out['status'], 'ok', out)
        checks = out['checks']
        self.assertTrue(checks['file_exists'])
        self.assertGreater(checks['size_bytes'], 0)
        self.assertTrue(checks['resolution_ok'])
        self.assertTrue(checks['duration_ok'])

    def test_missing_ffmpeg_is_unavailable_not_fake_success(self):
        ctx = ToolContext(Path(tempfile.mkdtemp()))
        ctx.ffmpeg = None
        out = render_and_check({'shots': [{'index': 0, 'seconds': 1}]}, ctx)
        self.assertEqual(out['status'], 'unavailable')
        self.assertEqual(out['reason'], 'ffmpeg_not_found')


class ArtifactStoreTests(unittest.TestCase):
    def test_key_is_stable_across_dict_order(self):
        store = ArtifactStore(Path(tempfile.mkdtemp()))
        a = store.path('t', {'x': 1, 'y': 2})
        b = store.path('t', {'y': 2, 'x': 1})
        self.assertEqual(a, b)

    def test_load_marks_reuse(self):
        store = ArtifactStore(Path(tempfile.mkdtemp()))
        store.save('t', {'x': 1}, {'status': 'ok'})
        loaded = store.load('t', {'x': 1})
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded['reused'])

    def test_different_arguments_produce_different_artifacts(self):
        store = ArtifactStore(Path(tempfile.mkdtemp()))
        self.assertNotEqual(store.path('t', {'x': 1}), store.path('t', {'x': 2}))


class RegistryTests(unittest.TestCase):
    def test_five_tools_with_openai_schemas(self):
        tools = build_tools()
        self.assertEqual([t.name for t in tools],
                         ['search_assets', 'write_script', 'make_storyboard',
                          'synthesize_tts', 'render_and_check'])
        for tool in tools:
            schema = tool.schema()
            self.assertEqual(schema['type'], 'function')
            self.assertEqual(schema['function']['name'], tool.name)
            self.assertIn('parameters', schema['function'])


if __name__ == '__main__':
    unittest.main()
