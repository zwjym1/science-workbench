"""The four numbers, and nothing else.

Task success rate, quality score, latency, cost. Quality is ``None`` unless a
rubric was scored, because averaging an unscored case into a quality mean is how
benchmarks end up flattering themselves.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class CaseRun:
    case_id: str
    status: str                       # ok | failed | exhausted | error
    passed: bool
    checks: list[dict] = field(default_factory=list)
    latency_s: float = 0.0
    prompt_tokens: int = 0            # estimate, see budget.estimate_tokens
    attempts: int = 0            # tool executions, including ones that failed
    reused: int = 0
    render_seconds: float = 0.0
    quality: float | None = None
    error: str = ''
    known_failure: bool = False

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def failed_checks(self) -> list[str]:
        return [c['name'] for c in self.checks if not c['ok']]


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def summarize(runs: list[CaseRun]) -> dict[str, Any]:
    total = len(runs)
    passed = sum(1 for r in runs if r.passed)
    scored = [r.quality for r in runs if r.quality is not None]
    latencies = [r.latency_s for r in runs]
    returns = {
        'cases': total,
        'passed': passed,
        'failed': total - passed,
        'success_rate': round(passed / total, 4) if total else 0.0,
        'quality_mean': round(statistics.fmean(scored), 3) if scored else None,
        'quality_scored_cases': len(scored),
        'quality_unscored_cases': total - len(scored),
        'latency_mean_s': round(statistics.fmean(latencies), 3) if latencies else 0.0,
        'latency_p50_s': _percentile(latencies, 0.5),
        'latency_p95_s': _percentile(latencies, 0.95),
        'prompt_tokens_estimate': sum(r.prompt_tokens for r in runs),
        'render_seconds': round(sum(r.render_seconds for r in runs), 3),
        'tool_calls': sum(r.attempts for r in runs),
        'reused_artifacts': sum(r.reused for r in runs),
        'error_cases': [r.case_id for r in runs if r.error],
        'failed_checks': {r.case_id: r.failed_checks for r in runs if not r.passed},
    }
    return returns


def compare(baseline: list[CaseRun], candidate: list[CaseRun]) -> dict[str, Any]:
    """Per-case diff between two runs of the same case set."""
    left = {r.case_id: r for r in baseline}
    right = {r.case_id: r for r in candidate}
    rows = []
    for case_id in sorted(set(left) | set(right)):
        a, b = left.get(case_id), right.get(case_id)
        rows.append({
            'case_id': case_id,
            'baseline_passed': bool(a and a.passed),
            'candidate_passed': bool(b and b.passed),
            'regressed': bool(a and a.passed and not (b and b.passed)),
            'fixed': bool(a and not a.passed and b and b.passed),
            'latency_delta_s': round((b.latency_s if b else 0.0)
                                     - (a.latency_s if a else 0.0), 3),
            'token_delta': (b.prompt_tokens if b else 0) - (a.prompt_tokens if a else 0),
        })
    return {
        'baseline': summarize(baseline),
        'candidate': summarize(candidate),
        'regressions': [r['case_id'] for r in rows if r['regressed']],
        'fixed': [r['case_id'] for r in rows if r['fixed']],
        'per_case': rows,
    }
