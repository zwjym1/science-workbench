import json
import tempfile
import unittest
from pathlib import Path

from clipbench.attribution import (CATEGORIES, attribute, distribution,
                                   render_report)


def write_trace(folder: Path, kinds: list[tuple[str, dict]], run_id='r1') -> Path:
    path = folder / f'{run_id}.jsonl'
    lines = []
    for index, (kind, payload) in enumerate(kinds, 1):
        lines.append(json.dumps({'run_id': run_id, 'seq': index, 'kind': kind,
                                 'payload': payload, 'ts': float(index)}))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


PLAN = ('plan', {'task': 'x'})


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_argument_error_is_argument_generation(self):
        path = write_trace(self.dir, [
            PLAN, ('error', {'tool': 'write_script',
                             'reason': 'invalid_arguments: citations required'}),
            ('final', {'text': 'gave up'})])
        self.assertEqual(attribute(path).primary, 'argument_generation')

    def test_unknown_tool_is_tool_selection(self):
        path = write_trace(self.dir, [
            PLAN, ('error', {'tool': 'nope', 'reason': 'unknown_tool:nope'}),
            ('final', {'text': 'x'})])
        self.assertEqual(attribute(path).primary, 'tool_selection')

    def test_render_fault_is_environment(self):
        path = write_trace(self.dir, [
            PLAN, ('error', {'tool': 'render_and_check',
                             'reason': 'ffmpeg_failed: no such file'})])
        self.assertEqual(attribute(path).primary, 'environment')

    def test_environment_outranks_downstream_errors(self):
        path = write_trace(self.dir, [
            PLAN,
            ('error', {'tool': 'write_script', 'reason': 'invalid_arguments: x'}),
            ('error', {'tool': 'render_and_check', 'reason': 'ffmpeg_failed: boom'})])
        self.assertEqual(attribute(path).primary, 'environment')

    def test_repeated_failure_after_compaction_is_context(self):
        path = write_trace(self.dir, [
            PLAN,
            ('replan', {'why': 'context_compacted', 'dropped_messages': 4}),
            ('error', {'tool': 'make_storyboard', 'reason': 'KeyError: sentences'}),
            ('error', {'tool': 'make_storyboard', 'reason': 'KeyError: sentences'})])
        self.assertEqual(attribute(path).primary, 'context_understanding')

    def test_repeated_failure_without_compaction_is_planning(self):
        path = write_trace(self.dir, [
            PLAN,
            ('error', {'tool': 'make_storyboard', 'reason': 'KeyError: sentences'}),
            ('error', {'tool': 'make_storyboard', 'reason': 'KeyError: sentences'})])
        self.assertEqual(attribute(path).primary, 'planning')

    def test_running_out_of_steps_is_planning(self):
        path = write_trace(self.dir, [PLAN, ('tool', {'tool': 'write_script'}),
                                      ('tool', {'tool': 'write_script'})])
        attribution = attribute(path)
        self.assertEqual(attribution.primary, 'planning')
        self.assertIn('ran out of steps', ' '.join(attribution.signals))

    def test_clean_tools_with_failed_checks_is_planning(self):
        path = write_trace(self.dir, [PLAN, ('tool', {'tool': 'write_script'}),
                                      ('final', {'text': 'done'})])
        attribution = attribute(path, failed_checks=['duration_s'])
        self.assertEqual(attribution.primary, 'planning')
        self.assertIn('missed constraints', ' '.join(attribution.signals))

    def test_healthy_run_is_not_attributed_to_anything(self):
        path = write_trace(self.dir, [PLAN, ('tool', {'tool': 'write_script'}),
                                      ('final', {'text': 'done'})])
        self.assertEqual(attribute(path, passed=True).primary, 'none')

    def test_failure_without_a_matching_rule_says_unclassified(self):
        path = write_trace(self.dir, [PLAN, ('error', {'tool': 't',
                                                       'reason': 'weird fault'})])
        self.assertEqual(attribute(path).primary, 'unclassified')

    def test_distribution_counts_every_category(self):
        healthy = attribute(write_trace(self.dir, [
            PLAN, ('final', {'text': 'ok'})], run_id='a'), passed=True)
        args = attribute(write_trace(self.dir, [
            PLAN, ('error', {'tool': 't', 'reason': 'invalid_arguments: x'})],
            run_id='b'))
        counts = distribution([healthy, args])
        self.assertEqual(set(counts), set(CATEGORIES))
        self.assertEqual(counts['argument_generation'], 1)
        self.assertEqual(sum(counts.values()), 1)

    def test_report_states_the_rule_layer_and_unclassified(self):
        items = [attribute(write_trace(self.dir, [
            PLAN, ('error', {'tool': 't', 'reason': 'invalid_arguments: x'})]))]
        text = render_report(items)
        self.assertIn('Failure attribution', text)
        self.assertIn('argument_generation', text)
        self.assertIn('not a model', text)


if __name__ == '__main__':
    unittest.main()
