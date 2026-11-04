"""Case definition and constraint checking.

A case is data, not code: the task text, the constraints it must satisfy, and an
optional rubric. Constraints are checked by rules here; a rubric is only used by
the judge in the next milestone, and its absence is reported as ``unscored``
rather than scored as zero.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

CONSTRAINT_KEYS = {'duration_s', 'shots', 'must_cite', 'min_assets',
                   'max_latency_s', 'render'}


@dataclass
class Case:
    id: str
    title: str
    task: str
    constraints: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    known_failure: bool = False
    rubric: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> 'Case':
        unknown = set(data.get('constraints') or {}) - CONSTRAINT_KEYS
        if unknown:
            raise ValueError(f'{data.get("id")}: unknown constraints {sorted(unknown)}')
        for key in ('id', 'title', 'task'):
            if not data.get(key):
                raise ValueError(f'case is missing {key!r}: {data!r}')
        return cls(**{k: data[k] for k in
                      ('id', 'title', 'task', 'constraints', 'tags',
                       'known_failure', 'rubric') if k in data})

    def as_dict(self) -> dict:
        return asdict(self)


def load_cases(folder: Path) -> list[Case]:
    cases = []
    for path in sorted(Path(folder).glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        records = data if isinstance(data, list) else [data]
        for record in records:
            cases.append(Case.from_dict(record))
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f'duplicate case ids: {sorted(duplicates)}')
    return cases


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ''

    def as_dict(self) -> dict:
        return asdict(self)


def check_constraints(case: Case, artifacts: dict[str, Any],
                      elapsed_s: float) -> list[Check]:
    """Rule layer of the judge: did the run actually satisfy the brief?"""
    checks: list[Check] = []
    constraints = case.constraints

    board = artifacts.get('make_storyboard') or {}
    render = artifacts.get('render_and_check') or {}
    script = artifacts.get('write_script') or {}
    assets = artifacts.get('search_assets') or {}

    if 'duration_s' in constraints:
        want = float(constraints['duration_s'])
        got = board.get('total_seconds')
        if got is None:
            checks.append(Check('duration_s', False, 'no storyboard produced'))
        else:
            checks.append(Check('duration_s', abs(float(got) - want) < 1.0,
                                f'want {want}, got {got}'))

    if 'shots' in constraints:
        want_shots = int(constraints['shots'])
        got_shots = len(board.get('shots') or [])
        checks.append(Check('shots', got_shots == want_shots,
                            f'want {want_shots}, got {got_shots}'))

    if constraints.get('must_cite'):
        sentences = script.get('sentences') or []
        missing = [s for s in sentences if not s.get('citation')]
        checks.append(Check('must_cite', bool(sentences) and not missing,
                            'no script' if not sentences
                            else f'{len(missing)} sentences without a citation'))

    if 'min_assets' in constraints:
        want_assets = int(constraints['min_assets'])
        got_assets = len(assets.get('assets') or [])
        checks.append(Check('min_assets', got_assets >= want_assets,
                            f'want >= {want_assets}, got {got_assets}'))

    if constraints.get('render'):
        status = render.get('status')
        checks.append(Check('render', status == 'ok', f'render status {status}'))
        if status == 'ok':
            probe = render.get('checks') or {}
            checks.append(Check('render_resolution', bool(probe.get('resolution_ok')),
                                str(probe.get('width')) + 'x' + str(probe.get('height'))))
            checks.append(Check('render_duration', bool(probe.get('duration_ok')),
                                f'actual {probe.get("actual_seconds")}'))

    if 'max_latency_s' in constraints:
        limit = float(constraints['max_latency_s'])
        checks.append(Check('max_latency_s', elapsed_s <= limit,
                            f'limit {limit}s, took {elapsed_s:.2f}s'))
    return checks
