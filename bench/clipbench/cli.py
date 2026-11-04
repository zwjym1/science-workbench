"""Command line entry point for the benchmark runner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clipagent.llm import OpenAICompatClient, ScriptedClient

from . import policy
from .case import load_cases
from .metrics import CaseRun
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

    meta = {'label': args.label,
            'model': policy.LABEL if args.client == 'scripted' else args.model_hint,
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
