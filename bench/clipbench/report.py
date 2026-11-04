"""Reports: one run to Markdown, two runs to a regression table."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import CaseRun, compare, summarize


def write_json(path: Path, runs: list[CaseRun], meta: dict[str, Any]) -> Path:
    payload = {'generated_at': datetime.now(timezone.utc).isoformat(),
               'meta': meta, 'summary': summarize(runs),
               'cases': [r.as_dict() for r in runs]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding='utf-8')
    return Path(path)


def _pct(value: float | None) -> str:
    return 'n/a' if value is None else f'{value * 100:.1f}%'


def render_markdown(runs: list[CaseRun], meta: dict[str, Any]) -> str:
    s = summarize(runs)
    lines = [
        f"# Evaluation report — {meta.get('label', 'run')}",
        '',
        f"- model: `{meta.get('model', 'unspecified')}`  ",
        f"- cases: {s['cases']}  ",
        f"- generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        '',
        '## Summary',
        '',
        '| metric | value |',
        '|---|---|',
        f"| task success rate | {_pct(s['success_rate'])} ({s['passed']}/{s['cases']}) |",
        f"| quality score | {'not scored (no rubric)' if s['quality_mean'] is None else s['quality_mean']} |",
        f"| latency p50 / p95 | {s['latency_p50_s']}s / {s['latency_p95_s']}s |",
        f"| latency mean | {s['latency_mean_s']}s |",
        f"| prompt tokens (estimate) | {s['prompt_tokens_estimate']} |",
        f"| render seconds | {s['render_seconds']}s |",
        f"| tool calls / reused artefacts | {s['tool_calls']} / {s['reused_artifacts']} |",
        '',
        '## Cases',
        '',
        '| case | status | passed | latency | failed checks |',
        '|---|---|---|---|---|',
    ]
    for run in runs:
        state = 'expected failure' if (not run.passed and run.known_failure) else \
                ('pass' if run.passed else 'fail')
        lines.append(f"| {run.case_id} | {run.status} | {state} | "
                     f"{run.latency_s}s | {', '.join(run.failed_checks) or '—'} |")
    lines += ['', '> Token counts are character-based estimates; '
                  'quality is left empty rather than scored when a case has no rubric.', '']
    return '\n'.join(lines)


def write_markdown(path: Path, runs: list[CaseRun], meta: dict[str, Any]) -> Path:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(render_markdown(runs, meta), encoding='utf-8')
    return Path(path)


def render_comparison(baseline: list[CaseRun], candidate: list[CaseRun],
                      meta: dict[str, Any]) -> str:
    diff = compare(baseline, candidate)
    a, b = diff['baseline'], diff['candidate']
    lines = [
        f"# Version comparison — {meta.get('baseline', 'baseline')} → "
        f"{meta.get('candidate', 'candidate')}",
        '',
        '| metric | baseline | candidate | delta |',
        '|---|---|---|---|',
    ]
    for key, label in (('success_rate', 'success rate'),
                       ('quality_mean', 'quality'),
                       ('latency_mean_s', 'latency mean (s)'),
                       ('latency_p95_s', 'latency p95 (s)'),
                       ('prompt_tokens_estimate', 'prompt tokens'),
                       ('render_seconds', 'render seconds')):
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            delta = 'n/a'
        elif isinstance(va, float):
            delta = f'{vb - va:+.4f}'
        else:
            delta = f'{vb - va:+d}'
        lines.append(f'| {label} | {va} | {vb} | {delta} |')
    lines += ['', f"Regressions: {', '.join(diff['regressions']) or 'none'}",
              '', f"Fixed: {', '.join(diff['fixed']) or 'none'}", '']
    return '\n'.join(lines)
