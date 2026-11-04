import json
import tempfile
import unittest
from pathlib import Path

from clipagent.budget import History, estimate_tokens, total_tokens
from clipagent.llm import ScriptedClient
from clipagent.loop import Agent
from clipagent.tools import ToolContext
from clipagent.trace import Trace


def shots(n=2, seconds=1.0):
    return [{'index': i, 'seconds': seconds} for i in range(n)]


HAPPY = [
    {'tool': 'write_script', 'args': {'topic': '水循环', 'duration_s': 20,
                                      'citations': ['IPCC']}},
    {'final': 'done'},
]


class HappyPathTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_runs_to_final_and_records_artifacts(self):
        result = Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('make a video')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.final, 'done')
        self.assertIn('write_script', result.artifacts)
        self.assertEqual(result.artifacts['write_script']['status'], 'ok')

    def test_trace_is_append_only_and_readable(self):
        result = Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('make a video')
        rows = Trace.read(Path(result.trace_path))
        kinds = [r['kind'] for r in rows]
        self.assertEqual(kinds[0], 'plan')
        self.assertIn('tool', kinds)
        self.assertEqual(kinds[-1], 'final')
        self.assertEqual([r['seq'] for r in rows], list(range(1, len(rows) + 1)))

    def test_model_receives_tool_schemas(self):
        client = ScriptedClient(list(HAPPY), record=True)
        Agent(client, workdir=self.dir).run('make a video')
        names = [t['function']['name'] for t in client.calls[0]['tools']]
        self.assertIn('render_and_check', names)
        self.assertEqual(len(names), 5)


class ReplanTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_invalid_arguments_are_observed_then_replanned(self):
        script = [
            {'tool': 'write_script', 'args': {'topic': '水循环'}},          # no citations
            {'tool': 'write_script', 'args': {'topic': '水循环', 'duration_s': 20,
                                              'citations': ['IPCC']}},
            {'final': 'recovered'},
        ]
        result = Agent(ScriptedClient(script), workdir=self.dir).run('task')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.final, 'recovered')
        rows = Trace.read(Path(result.trace_path))
        errors = [r for r in rows if r['kind'] == 'error']
        self.assertTrue(errors)
        self.assertIn('invalid_arguments', errors[0]['payload']['reason'])

    def test_invalid_arguments_are_not_retried(self):
        script = [{'tool': 'write_script', 'args': {'topic': '水循环'}},
                  {'final': 'gave up'}]
        result = Agent(ScriptedClient(script), workdir=self.dir,
                       max_attempts=3).run('task')
        self.assertEqual(result.attempts, 1)
        rows = Trace.read(Path(result.trace_path))
        errors = [r for r in rows if r['kind'] == 'error']
        self.assertEqual(len(errors), 1)

    def test_unknown_tool_does_not_crash_the_run(self):
        script = [{'tool': 'nonexistent', 'args': {}}, {'final': 'ok anyway'}]
        result = Agent(ScriptedClient(script), workdir=self.dir).run('task')
        self.assertEqual(result.status, 'ok')
        rows = Trace.read(Path(result.trace_path))
        reasons = [r['payload'].get('reason', '') for r in rows if r['kind'] == 'error']
        self.assertTrue(any('unknown_tool' in r for r in reasons))

    def test_repeated_failure_reaches_max_steps(self):
        script = [{'tool': 'write_script', 'args': {'topic': 'x'}} for _ in range(3)]
        result = Agent(ScriptedClient(script), workdir=self.dir, max_steps=3).run('task')
        self.assertEqual(result.status, 'exhausted')
        self.assertIn('max_steps', result.reason)


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_second_run_reuses_content_addressed_artifacts(self):
        first = Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('task')
        self.assertEqual(first.reused, 0)
        second = Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('task')
        self.assertEqual(second.reused, 1)
        self.assertTrue(second.artifacts['write_script']['reused'])

    def test_changed_arguments_are_not_reused(self):
        Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('task')
        script = [{'tool': 'write_script', 'args': {'topic': '光合作用',
                                                    'duration_s': 20,
                                                    'citations': ['IPCC']}},
                  {'final': 'done'}]
        other = Agent(ScriptedClient(script), workdir=self.dir).run('task')
        self.assertEqual(other.reused, 0)

    def test_reused_steps_cost_no_attempts(self):
        Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('task')
        second = Agent(ScriptedClient(list(HAPPY)), workdir=self.dir).run('task')
        self.assertEqual(second.attempts, 0)


class BudgetTests(unittest.TestCase):
    def test_cjk_costs_more_than_ascii(self):
        self.assertGreater(estimate_tokens('水循环' * 10), estimate_tokens('water' * 10))

    def test_compaction_keeps_anchors_and_recent_turns(self):
        history = History(max_tokens=40, keep_recent=3)
        history.append('system', 'S')
        history.append('user', 'goal')
        for i in range(10):
            history.observe('write_script', f'observation {i} ' + '填充内容' * 5)
        report = history.compact()
        self.assertGreater(report.dropped, 0)
        self.assertEqual(history.messages[0]['content'], 'S')
        self.assertEqual(history.messages[1]['content'], 'goal')
        self.assertEqual(history.messages[2]['role'], 'summary')
        self.assertLess(report.after, report.before)
        self.assertIn('write_script', report.tools_dropped)

    def test_compaction_reports_estimates_not_tokenizer_counts(self):
        history = History(max_tokens=10, keep_recent=1)
        history.append('system', 'S')
        history.append('user', 'goal')
        for i in range(4):
            history.observe('t', 'x' * 50)
        report = history.compact().as_dict()
        self.assertIn('estimate', report['note'])

    def test_small_history_is_left_alone(self):
        history = History(max_tokens=10_000)
        history.append('system', 'S')
        history.append('user', 'goal')
        self.assertEqual(history.compact().dropped, 0)


class LoopGuardTests(unittest.TestCase):
    def test_exhausted_script_surfaces_as_failed_run_not_a_hang(self):
        result = Agent(ScriptedClient([]), workdir=Path(tempfile.mkdtemp())).run('task')
        self.assertEqual(result.status, 'failed')
        self.assertIn('ScriptedClient exhausted', result.reason)


if __name__ == '__main__':
    unittest.main()
