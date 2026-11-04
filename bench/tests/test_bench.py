import json
import tempfile
import unittest
from pathlib import Path

from clipagent.llm import ScriptedClient
from clipbench import policy
from clipbench.case import Case, check_constraints, load_cases
from clipbench.metrics import CaseRun, compare, summarize
from clipbench.report import render_comparison, render_markdown
from clipbench.runner import Runner


def case(case_id='c1', **constraints):
    return Case(id=case_id, title='水循环', task='做一条视频',
                constraints=constraints)


class CaseLoadingTests(unittest.TestCase):
    def test_shipped_core_set_loads_with_unique_ids(self):
        cases = load_cases(Path(__file__).resolve().parent.parent
                           / 'clipbench' / 'cases')
        self.assertGreaterEqual(len(cases), 8)
        self.assertEqual(len({c.id for c in cases}), len(cases))

    def test_unknown_constraint_is_rejected_loudly(self):
        with self.assertRaises(ValueError) as ctx:
            Case.from_dict({'id': 'x', 'title': 't', 'task': 'k',
                            'constraints': {'durration_s': 30}})
        self.assertIn('unknown constraints', str(ctx.exception))

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(ValueError):
            Case.from_dict({'id': 'x', 'title': 't'})

    def test_duplicate_ids_are_rejected(self):
        folder = Path(tempfile.mkdtemp())
        (folder / 'a.json').write_text(json.dumps([
            {'id': 'dup', 'title': 'a', 'task': 'a'},
            {'id': 'dup', 'title': 'b', 'task': 'b'}]), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_cases(folder)

    def test_single_object_file_is_accepted(self):
        folder = Path(tempfile.mkdtemp())
        (folder / 'one.json').write_text(
            json.dumps({'id': 'solo', 'title': 'a', 'task': 'a'}), encoding='utf-8')
        self.assertEqual([c.id for c in load_cases(folder)], ['solo'])


class ConstraintTests(unittest.TestCase):
    def test_duration_mismatch_fails(self):
        c = case(duration_s=30)
        checks = check_constraints(c, {'make_storyboard': {'total_seconds': 40}}, 1.0)
        self.assertFalse(checks[0].ok)
        self.assertIn('want 30', checks[0].detail)

    def test_missing_artefact_is_a_failure_not_a_pass(self):
        checks = check_constraints(case(duration_s=30), {}, 1.0)
        self.assertFalse(checks[0].ok)
        self.assertIn('no storyboard', checks[0].detail)

    def test_citation_check_catches_one_uncited_sentence(self):
        c = case(must_cite=True)
        artifacts = {'write_script': {'sentences': [
            {'text': 'a', 'citation': 'x'}, {'text': 'b', 'citation': ''}]}}
        checks = check_constraints(c, artifacts, 1.0)
        self.assertFalse(checks[0].ok)
        self.assertIn('1 sentences', checks[0].detail)

    def test_render_check_reads_probe_output(self):
        c = case(render=True)
        artifacts = {'render_and_check': {'status': 'ok', 'checks': {
            'resolution_ok': True, 'duration_ok': False,
            'width': 320, 'height': 180, 'actual_seconds': 12.0}}}
        checks = {ch.name: ch for ch in check_constraints(c, artifacts, 1.0)}
        self.assertTrue(checks['render'].ok)
        self.assertTrue(checks['render_resolution'].ok)
        self.assertFalse(checks['render_duration'].ok)

    def test_latency_constraint(self):
        c = case(max_latency_s=10)
        self.assertFalse(check_constraints(c, {}, 11.0)[0].ok)
        self.assertTrue(check_constraints(c, {}, 9.0)[0].ok)


class MetricsTests(unittest.TestCase):
    def test_quality_is_none_when_nothing_is_scored(self):
        runs = [CaseRun('a', 'ok', True, latency_s=1.0),
                CaseRun('b', 'ok', False, latency_s=3.0)]
        summary = summarize(runs)
        self.assertEqual(summary['success_rate'], 0.5)
        self.assertIsNone(summary['quality_mean'])
        self.assertEqual(summary['quality_unscored_cases'], 2)

    def test_quality_mean_ignores_unscored_cases(self):
        runs = [CaseRun('a', 'ok', True, quality=4.0),
                CaseRun('b', 'ok', True, quality=None)]
        summary = summarize(runs)
        self.assertEqual(summary['quality_mean'], 4.0)
        self.assertEqual(summary['quality_scored_cases'], 1)

    def test_percentiles_are_stable(self):
        runs = [CaseRun(str(i), 'ok', True, latency_s=float(i)) for i in range(1, 11)]
        summary = summarize(runs)
        self.assertEqual(summary['latency_p50_s'], 5.0)
        self.assertEqual(summary['latency_p95_s'], 10.0)

    def test_compare_flags_regressions_and_fixes(self):
        baseline = [CaseRun('a', 'ok', True), CaseRun('b', 'ok', False)]
        candidate = [CaseRun('a', 'ok', False), CaseRun('b', 'ok', True)]
        diff = compare(baseline, candidate)
        self.assertEqual(diff['regressions'], ['a'])
        self.assertEqual(diff['fixed'], ['b'])

    def test_empty_run_set_does_not_divide_by_zero(self):
        self.assertEqual(summarize([])['success_rate'], 0.0)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _runner(self, **kw):
        return Runner(self.root,
                      lambda c: ScriptedClient(policy.build(c)),
                      width=160, height=90, fps=6, **kw)

    def test_pass_case_satisfies_its_constraints(self):
        run = self._runner().run_case(case(duration_s=8, shots=2, must_cite=True))
        self.assertEqual(run.status, 'ok')
        self.assertTrue(run.passed, run.checks)
        self.assertGreater(run.prompt_tokens, 0)

    def test_known_failure_is_recorded_as_failure_not_hidden(self):
        c = Case(id='kf', title='无来源', task='x',
                 constraints={'must_cite': True}, known_failure=True)
        run = self._runner().run_case(c)
        self.assertFalse(run.passed)
        self.assertTrue(run.known_failure)

    def test_result_is_cached_and_reused(self):
        c = case(duration_s=8, shots=2, must_cite=True)
        first = self._runner().run_case(c)
        self.assertTrue((self.root / c.id / 'result.json').is_file())
        second = self._runner().run_case(c)
        self.assertEqual(first.latency_s, second.latency_s)
        self.assertEqual(first.attempts, second.attempts)

    def test_force_reruns(self):
        c = case(duration_s=8, shots=2, must_cite=True)
        self._runner().run_case(c)
        rerun = self._runner(force=True).run_case(c)
        self.assertEqual(rerun.status, 'ok')

    def test_each_case_gets_its_own_directory(self):
        self._runner().run_all([case('a', duration_s=8, shots=2),
                                case('b', duration_s=8, shots=2)], progress=False)
        self.assertTrue((self.root / 'a' / 'runs').is_dir())
        self.assertTrue((self.root / 'b' / 'runs').is_dir())


class ReportTests(unittest.TestCase):
    def test_markdown_states_that_quality_was_not_scored(self):
        text = render_markdown([CaseRun('a', 'ok', True)], {'label': 'x'})
        self.assertIn('not scored (no rubric)', text)
        self.assertIn('character-based estimates', text)

    def test_comparison_lists_both_versions(self):
        text = render_comparison([CaseRun('a', 'ok', True)],
                                 [CaseRun('a', 'ok', False)],
                                 {'baseline': 'v1', 'candidate': 'v2'})
        self.assertIn('v1 → v2', text)
        self.assertIn('Regressions: a', text)


if __name__ == '__main__':
    unittest.main()
