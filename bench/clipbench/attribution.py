"""Failure attribution over a trace.

Reading a trace is a skill; writing the rule that reads a trace is the thing that
shows you have it. Five buckets, each with the signal that fired, and
``unclassified`` when nothing matches -- an attribution that always finds a
category is worse than no attribution, because it hides the cases the taxonomy
does not cover yet.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from clipagent.trace import Trace

CATEGORIES = ('planning', 'tool_selection', 'argument_generation',
              'context_understanding', 'environment', 'unclassified')
# A passing run has nothing to attribute; it is counted separately so the
# distribution describes failures instead of being diluted by successes.
NO_FAILURE = 'none'

ENVIRONMENT_HINTS = ('ffmpeg_failed', 'FileNotFoundError', 'PermissionError',
                     'unreachable', 'Timeout', 'ConnectionError')


@dataclass
class Attribution:
    case_id: str
    primary: str
    signals: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _errors(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r['kind'] == 'error']


def attribute(trace_path: Path, *, case_id: str = '',
              failed_checks: list[str] | None = None,
              passed: bool | None = None) -> Attribution:
    rows = Trace.read(trace_path)
    errors = _errors(rows)
    compactions = [r for r in rows if r['kind'] == 'replan'
                   and r['payload'].get('why') == 'context_compacted']
    tools = [r for r in rows if r['kind'] == 'tool']
    final = [r for r in rows if r['kind'] == 'final']
    case_id = case_id or (rows[0]['run_id'] if rows else 'unknown')

    if passed is True and not failed_checks:
        return Attribution(case_id=case_id, primary=NO_FAILURE,
                           signals=['run passed'])

    hits: list[tuple[str, str, dict]] = []

    for row in errors:
        reason = str(row['payload'].get('reason', ''))
        payload = row['payload']
        if reason.startswith('invalid_arguments'):
            hits.append(('argument_generation', 'tool rejected its arguments', payload))
        elif reason.startswith('unknown_tool'):
            hits.append(('tool_selection', 'model named a tool that does not exist', payload))
        elif any(hint in reason for hint in ENVIRONMENT_HINTS):
            hits.append(('environment', f'host fault: {reason[:80]}', payload))
        else:
            hits.append(('unclassified', f'unrecognised error: {reason[:80]}', payload))

    # Same tool failing repeatedly after a compaction points at lost context
    # rather than at the tool itself.
    per_tool: dict[str, int] = {}
    for row in errors:
        name = str(row['payload'].get('tool', ''))
        per_tool[name] = per_tool.get(name, 0) + 1
    repeated = {k: v for k, v in per_tool.items() if v >= 2}
    if repeated and compactions:
        hits.append(('context_understanding',
                     'repeated failure after history was compacted', dict(repeated)))

    if not final and len(rows) > 2:
        if repeated:
            hits.append(('planning', 'kept selecting an action that cannot succeed',
                         dict(repeated)))
        else:
            hits.append(('planning', 'ran out of steps without a final answer',
                         {'steps': len(tools)}))

    if failed_checks and not errors:
        hits.append(('planning', 'tools succeeded but the output missed constraints',
                     {'failed_checks': list(failed_checks)}))

    if not hits:
        return Attribution(case_id=case_id, primary='unclassified',
                           signals=['failed but no rule matched'])

    # Precedence: an environment fault explains everything downstream of it, so it
    # wins; then argument/selection errors, which are specific and actionable.
    order = ['environment', 'argument_generation', 'tool_selection',
             'context_understanding', 'planning', 'unclassified']
    primary = min((h[0] for h in hits), key=order.index)
    return Attribution(
        case_id=case_id,
        primary=primary,
        signals=[h[1] for h in hits],
        evidence=[{'category': h[0], 'signal': h[1], 'detail': h[2]} for h in hits],
    )


def attribute_results(results_path: Path) -> list[Attribution]:
    payload = json.loads(Path(results_path).read_text(encoding='utf-8'))
    out = []
    for case in payload.get('cases', []):
        trace_dir = Path(payload.get('meta', {}).get('workdir', '.')) / case['case_id'] / 'runs'
        traces = sorted(trace_dir.glob('*.jsonl'), key=lambda p: p.stat().st_mtime)
        if not traces:
            out.append(Attribution(case_id=case['case_id'], primary='unclassified',
                                   signals=['no trace found']))
            continue
        out.append(attribute(traces[-1], case_id=case['case_id'],
                             passed=case.get('passed'),
                             failed_checks=[c['name'] for c in case.get('checks', [])
                                            if not c['ok']]))
    return out


def distribution(attributions: list[Attribution]) -> dict[str, int]:
    """Count failures by category; passing runs are reported separately."""
    counts = {category: 0 for category in CATEGORIES}
    for item in attributions:
        if item.primary == NO_FAILURE:
            continue
        counts[item.primary] = counts.get(item.primary, 0) + 1
    return counts


def render_report(attributions: list[Attribution], *, examples: int = 3) -> str:
    counts = distribution(attributions)
    failures = sum(counts.values())
    passed = sum(1 for a in attributions if a.primary == NO_FAILURE)
    lines = ['# Failure attribution', '',
             f'{passed} of {len(attributions)} cases passed and are excluded from the '
             f'counts below; {failures} failed.', '',
             '| category | cases | share of failures |', '|---|---|---|']
    if not failures:
        lines.append('| — | 0 | n/a |')
    for category, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        if not count:
            continue
        lines.append(f'| {category} | {count} | {count / failures:.0%} |')
    lines += ['', '## Cases', '', '| case | primary | signals |', '|---|---|---|']
    for item in attributions:
        lines.append(f"| {item.case_id} | {item.primary} | "
                     f"{'; '.join(item.signals) or '—'} |")
    picked = [a for a in attributions
              if a.primary not in ('unclassified', NO_FAILURE)][:examples]
    if picked:
        lines += ['', f'## {len(picked)} cases in detail', '']
        for item in picked:
            lines.append(f'### {item.case_id} — {item.primary}')
            for evidence in item.evidence:
                lines.append(f"- ({evidence['category']}) {evidence['signal']}")
            lines.append('')
    lines += ['', '> Rules over trace signals, not a model. `unclassified` means the '
                  'taxonomy has no rule for it yet, which is information, not a gap to hide.', '']
    return '\n'.join(lines)
