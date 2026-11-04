import json
import tempfile
import unittest
from pathlib import Path

from clipagent.llm import ScriptedClient
from clipbench.judge import (DIMENSIONS, JUDGE_PROMPT, PROMPT_SHA, LLMJudge,
                             RubricJudge, calibrate, cohen_kappa, label_sheet,
                             quadratic_weighted_kappa, read_label_sheet)

CASE = {'case_id': 'c1', 'task': '做一条 40 秒视频',
        'checks': [{'name': 'duration_s', 'ok': True},
                   {'name': 'shots', 'ok': True},
                   {'name': 'must_cite', 'ok': False}]}


class PromptTests(unittest.TestCase):
    def test_prompt_hash_is_stable(self):
        import hashlib
        self.assertEqual(PROMPT_SHA,
                         hashlib.sha256(JUDGE_PROMPT.encode()).hexdigest()[:16])

    def test_prompt_pins_every_dimension(self):
        for dim in DIMENSIONS:
            self.assertIn(dim, JUDGE_PROMPT)

    def test_prompt_forbids_extra_output(self):
        self.assertIn('只输出 JSON', JUDGE_PROMPT)


class LLMJudgeTests(unittest.TestCase):
    def _judge(self, payload_text):
        client = ScriptedClient([{'final': payload_text}])
        return LLMJudge(client)

    def test_scores_are_parsed_and_weighted(self):
        judge = self._judge(json.dumps({'narrative': 4, 'accuracy': 5,
                                        'density': 3, 'constraint': 5,
                                        'rationale': 'ok'}))
        score = judge.score(CASE)
        self.assertEqual(score.dimensions['accuracy'], 5.0)
        self.assertAlmostEqual(score.weighted,
                               4 * 0.3 + 5 * 0.4 + 3 * 0.2 + 5 * 0.1, places=3)
        self.assertEqual(score.temperature, 0.0)
        self.assertEqual(score.prompt_sha, PROMPT_SHA)

    def test_out_of_range_scores_are_clamped(self):
        judge = self._judge(json.dumps({'narrative': 99, 'accuracy': -3,
                                        'density': 3, 'constraint': 3}))
        dims = judge.score(CASE).dimensions
        self.assertEqual(dims['narrative'], 5.0)
        self.assertEqual(dims['accuracy'], 1.0)

    def test_unparseable_output_is_flagged_not_guessed(self):
        score = self._judge('我觉得还行').score(CASE)
        self.assertEqual(score.rationale, 'unparseable_judge_output')
        self.assertEqual(score.weighted, 0.0)

    def test_json_inside_prose_is_still_extracted(self):
        text = '好的，评分如下：{"narrative":3,"accuracy":3,"density":3,"constraint":3}'
        self.assertEqual(self._judge(text).score(CASE).dimensions['narrative'], 3.0)

    def test_rubric_weights_are_normalised(self):
        rubric = {'dimensions': [{'id': 'narrative', 'weight': 0.4},
                                 {'id': 'accuracy', 'weight': 0.4}]}
        judge = LLMJudge(ScriptedClient([{'final': '{}'}]), rubric)
        self.assertAlmostEqual(sum(judge.weights.values()), 1.0)


class StandinTests(unittest.TestCase):
    def test_standin_is_labelled_as_such(self):
        score = RubricJudge().score(CASE)
        self.assertEqual(score.source, 'rubric-standin')
        self.assertIn('not a quality judgement', score.rationale)

    def test_standin_is_deterministic(self):
        a = RubricJudge().score(CASE).as_dict()
        b = RubricJudge().score(CASE).as_dict()
        self.assertEqual(a, b)


class KappaTests(unittest.TestCase):
    def test_perfect_agreement_is_one(self):
        self.assertEqual(cohen_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]), 1.0)
        self.assertEqual(quadratic_weighted_kappa([1, 5, 3], [1, 5, 3]), 1.0)

    def test_chance_level_agreement_is_zero(self):
        self.assertEqual(cohen_kappa([1, 2, 1, 2], [1, 1, 2, 2]), 0.0)

    def test_systematic_disagreement_is_negative(self):
        self.assertLess(cohen_kappa([1, 1, 5, 5], [5, 5, 1, 1]), 0)

    def test_weighted_penalises_large_gaps_harder(self):
        human = [3, 3, 4, 2, 3]
        one_off = [2, 3, 4, 2, 3]      # a single 1-point miss
        two_off = [1, 3, 4, 2, 3]      # a single 2-point miss
        self.assertGreater(quadratic_weighted_kappa(human, one_off),
                           quadratic_weighted_kappa(human, two_off))

    def test_empty_input_is_rejected(self):
        with self.assertRaises(ValueError):
            cohen_kappa([], [])
        with self.assertRaises(ValueError):
            cohen_kappa([1, 2], [1])


class CalibrationTests(unittest.TestCase):
    def test_insufficient_labels_do_not_claim_a_verdict(self):
        report = calibrate({'a': 4, 'b': 5}, {'a': 4, 'b': 5})
        self.assertEqual(report.verdict, 'insufficient_labels')

    def test_strong_agreement_is_reported_as_strong(self):
        ids = [f'c{i}' for i in range(10)]
        human = {cid: (i % 5) + 1 for i, cid in enumerate(ids)}
        judge = dict(human)
        report = calibrate(human, judge)
        self.assertEqual(report.kappa_quadratic, 1.0)
        self.assertEqual(report.verdict, 'strong')
        self.assertEqual(report.disagreements, [])

    def test_disagreements_are_listed_with_both_scores(self):
        human = {f'c{i}': 3 for i in range(10)}
        judge = {f'c{i}': 3 for i in range(10)}
        judge['c3'] = 5
        report = calibrate(human, judge)
        self.assertEqual(report.disagreements[0]['case_id'], 'c3')
        self.assertAlmostEqual(report.mean_absolute_error, 0.2, places=3)

    def test_only_overlapping_cases_are_compared(self):
        report = calibrate({'a': 4, 'b': 4}, {'b': 4, 'z': 1})
        self.assertEqual(report.n, 1)

    def test_missing_overlap_is_an_error_not_a_zero(self):
        with self.assertRaises(ValueError):
            calibrate({'a': 4}, {'b': 4})


class LabelSheetTests(unittest.TestCase):
    def test_sheet_round_trips(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / 'labels.csv'
        label_sheet(['c1', 'c2'], path)
        self.assertIn('c1,,', path.read_text(encoding='utf-8'))
        path.write_text('case_id,human_score_1to5,note\nc1,4,ok\nc2,2,\n', encoding='utf-8')
        self.assertEqual(read_label_sheet(path), {'c1': 4, 'c2': 2})

    def test_blank_rows_are_ignored(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / 'labels.csv'
        path.write_text('case_id,human_score_1to5,note\nc1,,\nc2,5,x\n', encoding='utf-8')
        self.assertEqual(read_label_sheet(path), {'c2': 5})


class CalibrationCliTests(unittest.TestCase):
    def test_label_sheet_has_both_columns_blank(self):
        from clipbench.cli import cmd_label_sheet
        import argparse
        folder = Path(tempfile.mkdtemp())
        out = folder / 'labels.csv'
        code = cmd_label_sheet(argparse.Namespace(
            cases=str(Path(__file__).resolve().parent.parent / 'clipbench' / 'cases'),
            out=str(out), print_prompt=False))
        self.assertEqual(code, 0)
        lines = out.read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[0], 'case_id,human_score_1to5,judge_score_1to5,note')
        self.assertGreaterEqual(len(lines), 11, 'need at least 10 rows to calibrate')
        self.assertTrue(all(line.endswith(',,,') for line in lines[1:]))

    def test_calibrate_reads_two_columns_and_reports_kappa(self):
        from clipbench.cli import cmd_calibrate
        import argparse
        folder = Path(tempfile.mkdtemp())
        sheet = folder / 'labels.csv'
        rows = ['case_id,human_score_1to5,judge_score_1to5,note']
        for i in range(1, 11):
            rows.append(f'c{i},{i % 5 + 1},{i % 5 + 1},')
        sheet.write_text('\n'.join(rows) + '\n', encoding='utf-8')
        out = folder / 'calibration.md'
        code = cmd_calibrate(argparse.Namespace(sheet=str(sheet), out=str(out)))
        self.assertEqual(code, 0)
        text = out.read_text(encoding='utf-8')
        self.assertIn('cases compared: 10', text)
        self.assertIn('strong', text)

    def test_calibrate_refuses_an_empty_sheet(self):
        from clipbench.cli import cmd_calibrate
        import argparse
        folder = Path(tempfile.mkdtemp())
        sheet = folder / 'labels.csv'
        sheet.write_text('case_id,human_score_1to5,judge_score_1to5,note\n', encoding='utf-8')
        self.assertEqual(cmd_calibrate(argparse.Namespace(sheet=str(sheet), out='')), 2)


if __name__ == '__main__':
    unittest.main()
