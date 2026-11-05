"""Command line entry point for the benchmark runner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clipagent.llm import OpenAICompatClient, ScriptedClient

from . import policy
from .case import load_cases
from .metrics import CaseRun, summarize
from .report import render_comparison, write_json, write_markdown
from .runner import Runner

DEFAULT_CASES = Path(__file__).resolve().parent / 'cases'


def _scripted_factory():
    def factory(case):
        return ScriptedClient(policy.build(case))
    return factory


def _model_factory():
    client = OpenAICompatClient.from_env()
    if client is None:
        print('set CLIPAGENT_BASE_URL and CLIPAGENT_MODEL, or use --client scripted',
              file=sys.stderr)
        raise SystemExit(2)

    def factory(case):                       # one client per case keeps state clean
        return OpenAICompatClient(base_url=client.base_url, model=client.model,
                                  api_key=client.api_key,
                                  temperature=client.temperature)
    return factory


def cmd_run(args) -> int:
    cases = load_cases(Path(args.cases))
    if args.only:
        wanted = set(args.only.split(','))
        cases = [c for c in cases if c.id in wanted]
    if not cases:
        print('no cases matched', file=sys.stderr)
        return 2

    factory = _scripted_factory() if args.client == 'scripted' else _model_factory()
    runner = Runner(Path(args.workdir), factory, max_steps=args.max_steps,
                    force=args.force)
    runs = runner.run_all(cases, progress=not args.quiet)

    from .judge import PROMPT_SHA
    meta = {'label': args.label,
            'model': policy.LABEL if args.client == 'scripted' else args.model_hint,
            'judge_prompt_sha': PROMPT_SHA,
            'case_file': str(args.cases), 'workdir': str(Path(args.workdir).resolve())}
    out = Path(args.out)
    write_json(out / 'results.json', runs, meta)
    write_markdown(out / 'report.md', runs, meta)

    from .attribution import attribute_results, render_report as render_attr
    (out / 'attribution.md').write_text(
        render_attr(attribute_results(out / 'results.json')), encoding='utf-8')

    print(f'\nwrote results.json, report.md and attribution.md under {out}')
    return 0


def cmd_compare(args) -> int:
    def load(path: Path) -> list[CaseRun]:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        return [CaseRun(**c) for c in payload['cases']]

    baseline, candidate = load(Path(args.baseline)), load(Path(args.candidate))
    meta = {'baseline': args.baseline, 'candidate': args.candidate}
    text = render_comparison(baseline, candidate, meta)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
        print(f'\nwrote {args.out}')
    return 0


def cmd_attribute(args) -> int:
    from .attribution import attribute_results, render_report

    items = attribute_results(Path(args.results))
    text = render_report(items, examples=args.examples)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
        print(f'\nwrote {args.out}')
    return 0


def _judge_client():
    """Judge endpoint, separate from the agent model when JUDGE_* is set."""
    import os
    from clipagent.llm import OpenAICompatClient
    base = os.environ.get('JUDGE_BASE_URL') or os.environ.get('CLIPAGENT_BASE_URL')
    model = os.environ.get('JUDGE_MODEL') or os.environ.get('CLIPAGENT_MODEL')
    key = os.environ.get('JUDGE_API_KEY') or os.environ.get('CLIPAGENT_API_KEY', '')
    if not base or not model:
        return None, None
    return OpenAICompatClient(base_url=base.rstrip('/'), model=model,
                              api_key=key, timeout=90), model


def _latest_artifact(workdir: Path, case_id: str, tool: str) -> dict:
    folder = Path(workdir) / case_id / 'artifacts'
    manifests = sorted(folder.glob(tool + '-*/manifest.json'),
                       key=lambda p: p.stat().st_mtime)
    if not manifests:
        return {}
    return json.loads(manifests[-1].read_text(encoding='utf-8'))


def cmd_score(args) -> int:
    """Score finished runs with the judge; emits a human/judge score sheet."""
    import csv
    from .case import load_cases
    from .judge import CodexJudge, LLMJudge, RubricJudge

    results = json.loads(Path(args.results).read_text(encoding='utf-8'))
    runs = results['cases']
    cases = {c.id: c for c in load_cases(Path(args.cases))}

    if args.judge == 'none':
        judge, model = None, 'not run'
    elif args.judge == 'codex':
        judge = CodexJudge(Path(args.workdir) / '.judge')
        model = f'codex-cli:{judge.model}'
    elif args.judge == 'rubric':
        judge, model = RubricJudge(), 'rubric-standin (not a quality judgement)'
    else:
        client, model = _judge_client()
        if client is None:
            print('set JUDGE_BASE_URL/JUDGE_MODEL (or CLIPAGENT_*), '
                  'or use --judge codex (CLI) / rubric / none', file=sys.stderr)
            return 2
        judge = LLMJudge(client)

    wanted = {c.strip() for c in (getattr(args, 'only', '') or '').split(',')
              if c.strip()}
    rows, detail = [], []
    payloads = []
    for run in runs:
        if wanted and run['case_id'] not in wanted:
            continue
        case = cases.get(run['case_id'])
        script = _latest_artifact(Path(args.workdir), run['case_id'], 'write_script')
        if not case or not script:
            continue
        board = _latest_artifact(Path(args.workdir), run['case_id'], 'make_storyboard')
        payload = {
            'case_id': run['case_id'], 'task': case.task,
            'constraints': case.constraints,
            'checks': run.get('checks') or [],
            'sentences': (script.get('sentences') or [])[:8],
            'shots': (board.get('shots') or [])[:12],
        }
        payloads.append(payload)
        if judge is None:
            rows.append({'case_id': run['case_id'], 'human_score_1to5': '',
                         'judge_score_1to5': '', 'note': ''})
            continue
        score = judge.score(payload)
        rows.append({'case_id': run['case_id'],
                     'human_score_1to5': '',
                     'judge_score_1to5': round(score.weighted, 2),
                     'note': score.rationale[:80]})
        detail.append({**score.as_dict(), 'model': model})

    if not rows:
        print('no scored runs: no write_script artifact under the workdir', file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['case_id', 'human_score_1to5',
                                                    'judge_score_1to5', 'note'])
        writer.writeheader()
        writer.writerows(rows)
    out.with_suffix('.json').write_text(
        json.dumps({'model': model, 'scores': detail}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    if judge is None:
        print(f'wrote {len(rows)} rows with both score columns blank (no judge run)')
    else:
        mean = sum(r['judge_score_1to5'] for r in rows) / len(rows)
        print(f'scored {len(rows)} cases with {model}; judge mean {mean:.2f}/5')
    print(f'wrote {out} and {out.with_suffix(".json")}')
    if getattr(args, 'html', ''):
        from html import escape
        blocks = []
        for payload in payloads:
            checks = ' '.join(
                f"<span class='{'ok' if c['ok'] else 'bad'}'>{escape(c['name'])}</span>"
                for c in payload['checks'])
            sentences = ''.join(
                f"<li>{escape(str(s.get('beat', '')))}：{escape(str(s.get('text', '')))} "
                f"<em>[{escape(str(s.get('citation') or '无引用'))}]</em></li>"
                for s in payload['sentences'])
            shots = '、'.join(
                f"{escape(str(s.get('index')))}:{escape(str(s.get('asset_id') or '无素材'))}"
                for s in payload['shots'])
            blocks.append(
                f"<section><h2>{escape(payload['case_id'])}</h2>"
                f"<p class='task'>{escape(payload['task'])}</p>"
                f"<p>约束：{escape(json.dumps(payload['constraints'], ensure_ascii=False))}</p>"
                f"<p>规则检查：{checks}</p><ol>{sentences}</ol>"
                f"<p class='hint'>镜头/素材：{shots or '—'}</p>"
                f"<p class='hint'>看完这一条，到 CSV 的 human_score_1to5 列打 1-5 分</p></section>")
        page = (
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<title>人工评分表</title><style>'
            'body{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;'
            'line-height:1.6;padding:0 16px}h2{font-size:18px;margin-bottom:4px}'
            'section{border-bottom:1px solid #ddd;padding:16px 0}'
            '.task{color:#333}.hint{color:#888;font-size:12px}'
            '.ok{color:#0a7;margin-right:8px}.bad{color:#c33;margin-right:8px}'
            'table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px 8px}'
            '</style><h1>人工评分表（1-5 分）</h1>'
            '<p><b>只评脚本与分镜本身</b>，不要因为时长/引用合规就加分——那些规则层已经查过，'
            '写在每条下面仅供你判断上下文。</p>'
            '<table><tr><th>分</th><th>含义</th></tr>'
            '<tr><td>5</td><td>叙事完整、事实准确、信息密度高，几乎不用改</td></tr>'
            '<tr><td>4</td><td>整体可用，个别句子空泛或衔接生硬</td></tr>'
            '<tr><td>3</td><td>能看懂，但像模板拼出来，缺少具体信息</td></tr>'
            '<tr><td>2</td><td>有明显错误、重复或跑题，需要重写</td></tr>'
            '<tr><td>1</td><td>不可用</td></tr></table>'
            '<p>先独立打分，再看 judge 列；两者不一致正是 kappa 要量的东西。</p>'
            + ''.join(blocks) + '</html>')
        Path(args.html).write_text(page, encoding='utf-8')
        print(f'wrote {args.html} for human scoring')
    return 0


def cmd_rebuild(args) -> int:
    """Rebuild results.json from per-case result files.

    Useful after rerunning a single case by hand, and after an interrupted
    batch: the per-case files are the source of truth, the batch summary is
    derived.
    """
    from .case import load_cases

    cases = load_cases(Path(args.cases))
    runs = []
    for case in cases:
        path = Path(args.workdir) / case.id / 'result.json'
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        runs.append(CaseRun(**{k: v for k, v in data.items()
                               if k in CaseRun.__dataclass_fields__}))
    if not runs:
        print(f'no result.json under {args.workdir}', file=sys.stderr)
        return 2
    out = Path(args.out)
    meta = {'label': args.label, 'model': args.model,
            'case_file': str(args.cases), 'rebuilt': True}
    write_json(out / 'results.json', runs, meta)
    write_markdown(out / 'report.md', runs, meta)
    s = summarize(runs)
    print(f'rebuilt {s["cases"]} cases: {s["passed"]} passed, '
          f'core {s["success_rate_core"]}')
    return 0


def cmd_matrix(args) -> int:
    """Run the same case set once per model and write one comparison table."""
    import os
    from clipagent.llm import OpenAICompatClient
    from .case import load_cases
    from .report import render_matrix
    from .runner import Runner

    base = os.environ.get('CLIPAGENT_BASE_URL')
    key = os.environ.get('CLIPAGENT_API_KEY', '')
    if not base:
        print('set CLIPAGENT_BASE_URL and CLIPAGENT_API_KEY', file=sys.stderr)
        return 2
    models = [m.strip() for m in args.models.split(',') if m.strip()]
    if not models:
        print('--models is empty', file=sys.stderr)
        return 2
    cases = load_cases(Path(args.cases))
    out = Path(args.out)
    rows = []
    for model in models:
        slug = model.replace('/', '__').replace(':', '_')
        folder = out / slug
        runner = Runner(Path(args.workdir) / slug,
                        lambda case, m=model: OpenAICompatClient(
                            base_url=base.rstrip('/'), model=m, api_key=key,
                            timeout=args.timeout),
                        max_steps=args.max_steps, force=args.force)
        runs = runner.run_all(cases, progress=not args.quiet)
        meta = {'label': model, 'model': model, 'case_file': str(args.cases),
                'workdir': str(Path(args.workdir) / slug)}
        write_json(folder / 'results.json', runs, meta)
        write_markdown(folder / 'report.md', runs, meta)
        from .attribution import attribute_results, render_report
        (folder / 'attribution.md').write_text(
            render_report(attribute_results(folder / 'results.json')), encoding='utf-8')
        rows.append({'model': model, 'summary': summarize(runs)})
        print(f'[{model}] {rows[-1]["summary"]["passed"]}/{len(runs)} passed')
    text = render_matrix(rows, {'label': args.label, 'cases': len(cases),
                                'judge': 'see clipbench score per model'})
    (out / 'matrix.md').write_text(text, encoding='utf-8')
    print(text)
    return 0


def cmd_label_sheet(args) -> int:
    """Emit a sheet with both columns empty; only a human fills 'human'."""
    from .case import load_cases
    from .judge import JUDGE_PROMPT, PROMPT_SHA, label_sheet

    cases = load_cases(Path(args.cases))
    ids = [c.id for c in cases]
    label_sheet(ids, args.out)
    print(f'wrote {args.out} with {len(ids)} rows (human_score_1to5 left blank)')
    print(f'judge prompt sha256: {PROMPT_SHA}')
    if args.print_prompt:
        print('\n--- frozen judge prompt ---\n' + JUDGE_PROMPT)
    return 0


def cmd_calibrate(args) -> int:
    """Agreement between a human sheet and judge scores, from one CSV.

    The sheet has case_id, human_score_1to5, judge_score_1to5. The judge column
    must come from a real judge run; this command only measures agreement and
    never fills either column itself.
    """
    import csv
    from .judge import calibrate

    human: dict[str, int] = {}
    judge: dict[str, int] = {}
    with Path(args.sheet).open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            cid = (row.get('case_id') or '').strip()
            if not cid:
                continue
            if (row.get('human_score_1to5') or '').strip():
                human[cid] = round(float(row['human_score_1to5']))
            if (row.get('judge_score_1to5') or '').strip():
                judge[cid] = round(float(row['judge_score_1to5']))
    if not human or not judge:
        print('need at least one human row and one judge row', file=sys.stderr)
        return 2
    report = calibrate(human, judge)
    lines = [f'# Judge calibration', '',
             f'- cases compared: {report.n}',
             f'- verdict: **{report.verdict}** (needs n >= 10 to be meaningful)',
             f"- Cohen's kappa (nominal): {report.kappa_nominal}",
             f'- quadratic weighted kappa: {report.kappa_quadratic}',
             f'- mean absolute error: {report.mean_absolute_error}', '',
             'Disagreements say where the rubric is ambiguous; revise the rubric,',
             're-score, and keep both sheets rather than editing history.',
             '']
    for item in report.disagreements:
        lines.append(f"- {item['case_id']}: human {item['human']} / judge {item['judge']}")
    text = '\n'.join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
        print(f'\nwrote {args.out}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='clipbench', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    run = sub.add_parser('run', help='run a case set')
    run.add_argument('--cases', default=str(DEFAULT_CASES))
    run.add_argument('--workdir', default='.bench-work')
    run.add_argument('--out', default='.bench-out')
    run.add_argument('--client', choices=['scripted', 'model'], default='scripted')
    run.add_argument('--model-hint', default='(from environment)')
    run.add_argument('--label', default='local run')
    run.add_argument('--only', default='', help='comma separated case ids')
    run.add_argument('--max-steps', type=int, default=12)
    run.add_argument('--force', action='store_true', help='ignore cached results')
    run.add_argument('--quiet', action='store_true')
    run.set_defaults(func=cmd_run)

    cmp = sub.add_parser('compare', help='diff two result files')
    cmp.add_argument('baseline')
    cmp.add_argument('candidate')
    cmp.add_argument('--out', default='')
    cmp.set_defaults(func=cmd_compare)

    attr = sub.add_parser('attribute', help='classify failures from traces')
    attr.add_argument('results')
    attr.add_argument('--out', default='')
    attr.add_argument('--examples', type=int, default=3)
    attr.set_defaults(func=cmd_attribute)

    sheet = sub.add_parser('label-sheet', help='emit a blank human/judge score sheet')
    sheet.add_argument('--cases', default=str(DEFAULT_CASES))
    sheet.add_argument('--out', default='labels.csv')
    sheet.add_argument('--print-prompt', action='store_true',
                       help='print the frozen judge prompt and exit')
    sheet.set_defaults(func=cmd_label_sheet)

    cal = sub.add_parser('calibrate', help='measure human/judge agreement from a sheet')
    cal.add_argument('sheet')
    cal.add_argument('--out', default='')
    cal.set_defaults(func=cmd_calibrate)

    score = sub.add_parser('score', help='run the judge over finished runs')
    score.add_argument('--results', default='.bench-out/results.json')
    score.add_argument('--workdir', default='.bench-work')
    score.add_argument('--cases', default=str(DEFAULT_CASES))
    score.add_argument('--judge', choices=['llm', 'codex', 'rubric', 'none'], default='llm')
    score.add_argument('--only', default='', help='comma separated case ids')
    score.add_argument('--out', default='.bench-out/judge-scores.csv')
    score.add_argument('--html', default='', help='write a human scoring page')
    score.set_defaults(func=cmd_score)

    rebuild = sub.add_parser('rebuild', help='rebuild a batch summary from case files')
    rebuild.add_argument('--workdir', required=True)
    rebuild.add_argument('--out', required=True)
    rebuild.add_argument('--cases', default=str(DEFAULT_CASES))
    rebuild.add_argument('--label', default='rebuilt from case files')
    rebuild.add_argument('--model', default='(unspecified)')
    rebuild.set_defaults(func=cmd_rebuild)

    matrix = sub.add_parser('matrix', help='run one case set across several models')
    matrix.add_argument('--models', required=True, help='comma separated model ids')
    matrix.add_argument('--cases', default=str(DEFAULT_CASES))
    matrix.add_argument('--workdir', default='.bench-work')
    matrix.add_argument('--out', default='.bench-matrix')
    matrix.add_argument('--label', default='model comparison')
    matrix.add_argument('--max-steps', type=int, default=12)
    matrix.add_argument('--timeout', type=int, default=90)
    matrix.add_argument('--force', action='store_true')
    matrix.add_argument('--quiet', action='store_true')
    matrix.set_defaults(func=cmd_matrix)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
