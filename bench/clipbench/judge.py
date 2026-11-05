"""Third layer of the judge: subjective quality, scored by a model.

The first two layers (rules, constraint checks) live in ``case.py``; they are
cheap, deterministic and already done. This layer is only for what a rule cannot
decide -- narrative coherence, information density -- and it is built so its
result can be audited:

* the prompt is a frozen string, and its SHA-256 is stored with every score, so
  "we changed the prompt" is a visible event rather than a quiet drift;
* temperature is pinned to 0 and recorded;
* every score must be compared against human labels before it is trusted, via
  Cohen's kappa, which is computed here rather than asserted in a slide.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Protocol, Sequence

JUDGE_PROMPT = """你是科普短视频的质量评审。只评价给定的四个维度，不要评价风格偏好。

评分维度（每项 1-5 分，整数）：
- narrative：四个节拍是否构成从现象到边界的完整叙事，而不是四句并列的话。
- accuracy：每个事实句是否有来源，且来源是否支持该句（有引用但引用不支持 = 低分）。
- density：单位时长内是否有实质信息，有无空话或重复。
- constraint：是否满足给定的时长、镜头数等硬约束。

只输出 JSON，不要解释之外的内容：
{"narrative": n, "accuracy": n, "density": n, "constraint": n, "rationale": "一句话"}
"""

PROMPT_SHA = hashlib.sha256(JUDGE_PROMPT.encode('utf-8')).hexdigest()[:16]
DIMENSIONS = ('narrative', 'accuracy', 'density', 'constraint')


class Judge(Protocol):
    def score(self, case_payload: dict) -> dict: ...


@dataclass
class Score:
    case_id: str
    dimensions: dict[str, float]
    weighted: float
    rationale: str = ''
    prompt_sha: str = PROMPT_SHA
    temperature: float = 0.0
    source: str = 'llm'

    def as_dict(self) -> dict:
        return asdict(self)


def _weights(rubric: dict | None) -> dict[str, float]:
    defaults = {'narrative': 0.3, 'accuracy': 0.4, 'density': 0.2, 'constraint': 0.1}
    if not rubric:
        return defaults
    out = dict(defaults)
    for dim in rubric.get('dimensions') or []:
        if dim.get('id') in out and isinstance(dim.get('weight'), (int, float)):
            out[dim['id']] = float(dim['weight'])
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


def _clamp(value: float) -> float:
    return max(1.0, min(5.0, float(value)))


class LLMJudge:
    """One model call per case, temperature 0, frozen prompt."""

    def __init__(self, client, rubric: dict | None = None):
        self.client = client
        self.weights = _weights(rubric)

    def score(self, case_payload: dict) -> Score:
        prompt = JUDGE_PROMPT + '\n\n待评内容：\n' + json.dumps(
            case_payload, ensure_ascii=False, indent=2)
        decision = self.client.decide(
            [{'role': 'system', 'content': prompt},
             {'role': 'user', 'content': '请评分并只返回 JSON。'}], [])
        text = decision.get('final', '') if isinstance(decision, dict) else str(decision)
        data = _extract_json(text)
        if data is None:
            return Score(case_id=str(case_payload.get('case_id', '')),
                         dimensions={}, weighted=0.0,
                         rationale='unparseable_judge_output', source='llm')
        dims = {k: _clamp(data.get(k, 0) or 0) for k in DIMENSIONS}
        weighted = sum(dims[k] * self.weights[k] for k in DIMENSIONS)
        return Score(case_id=str(case_payload.get('case_id', '')), dimensions=dims,
                     weighted=round(weighted, 3),
                     rationale=str(data.get('rationale', ''))[:200])


def _extract_json(text: str) -> dict | None:
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class RubricJudge:
    """Deterministic stand-in used by tests and by offline dry runs.

    It scores exactly the things the rule layer can see, which makes it useless
    as a quality judge and useful as a fixture -- and its name says so.
    """

    def __init__(self, rubric: dict | None = None):
        self.weights = _weights(rubric)

    def score(self, case_payload: dict) -> Score:
        checks = case_payload.get('checks') or []
        ok = sum(1 for c in checks if c.get('ok'))
        ratio = ok / len(checks) if checks else 0.0
        base = 1.0 + 4.0 * ratio
        dims = {k: round(base, 3) for k in DIMENSIONS}
        return Score(case_id=str(case_payload.get('case_id', '')), dimensions=dims,
                     weighted=round(base, 3),
                     rationale='rule-derived stand-in, not a quality judgement',
                     source='rubric-standin')


CODEX_SCHEMA = {
    'type': 'object',
    'properties': {
        'narrative': {'type': 'number'},
        'accuracy': {'type': 'number'},
        'density': {'type': 'number'},
        'constraint': {'type': 'number'},
        'rationale': {'type': 'string'},
    },
    'required': ['narrative', 'accuracy', 'density', 'constraint', 'rationale'],
    'additionalProperties': False,
}


def _codex_model() -> str:
    try:
        text = (Path.home() / '.codex' / 'config.toml').read_text(encoding='utf-8')
    except OSError:
        return 'unknown'
    match = re.search(r'^model\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else 'unknown'


class CodexJudge:
    """Judge through the Codex CLI, for when no API quota is left.

    Same frozen prompt and a JSON schema, so the output is parseable without
    scraping the CLI banner. The model and prompt hash are recorded with every
    score; a CLI run is not silently equated with an API run.
    """

    def __init__(self, workdir: Path):
        self.exe = shutil.which('codex')
        if not self.exe:
            raise RuntimeError('codex CLI not found on PATH')
        self.dir = Path(workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.schema = self.dir / 'judge-schema.json'
        self.schema.write_text(json.dumps(CODEX_SCHEMA), encoding='utf-8')
        self.out = self.dir / 'judge-out.json'
        self.model = _codex_model()
        self.weights = _weights(None)

    def score(self, case_payload: dict) -> Score:
        prompt = JUDGE_PROMPT + '\n\n待评内容：\n' + json.dumps(
            case_payload, ensure_ascii=False, indent=2)
        if self.out.exists():
            self.out.unlink()
        command = [self.exe, 'exec', '--skip-git-repo-check',
                   '-C', str(self.dir), '-s', 'read-only',
                   '--output-schema', str(self.schema),
                   '-o', str(self.out), '-']
        try:
            # Codex reads stdin as UTF-8; Windows' default text encoding is the
            # ANSI code page, so the prompt must be encoded explicitly.
            subprocess.run(command, input=prompt, text=True, encoding='utf-8',
                           capture_output=True, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Score(case_id=str(case_payload.get('case_id', '')), dimensions={},
                         weighted=0.0, rationale=f'codex_invocation_failed: {exc}'[:200],
                         source='codex')
        if not self.out.is_file():
            return Score(case_id=str(case_payload.get('case_id', '')), dimensions={},
                         weighted=0.0, rationale='codex_wrote_no_output',
                         source='codex')
        try:
            data = json.loads(self.out.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            return Score(case_id=str(case_payload.get('case_id', '')), dimensions={},
                         weighted=0.0, rationale=f'unparseable_codex_output: {exc}'[:200],
                         source='codex')
        dims = {k: _clamp(data.get(k, 0) or 0) for k in DIMENSIONS}
        weighted = sum(dims[k] * self.weights[k] for k in DIMENSIONS)
        return Score(case_id=str(case_payload.get('case_id', '')), dimensions=dims,
                     weighted=round(weighted, 3),
                     rationale=str(data.get('rationale', ''))[:200],
                     source=f'codex:{self.model}')


# --------------------------------------------------------------------------
# agreement
# --------------------------------------------------------------------------
def cohen_kappa(a: Sequence[int], b: Sequence[int]) -> float:
    """Nominal agreement corrected for chance."""
    if len(a) != len(b) or not a:
        raise ValueError('two non-empty label lists of equal length are required')
    labels = sorted(set(a) | set(b))
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if expected == 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 4)


def quadratic_weighted_kappa(a: Sequence[int], b: Sequence[int],
                             min_rating: int = 1, max_rating: int = 5) -> float:
    """Agreement for ordered scores; penalises a 1-vs-5 miss much harder."""
    if len(a) != len(b) or not a:
        raise ValueError('two non-empty label lists of equal length are required')
    n = len(a)
    size = max_rating - min_rating + 1

    observed = [[0] * size for _ in range(size)]
    for x, y in zip(a, b):
        observed[x - min_rating][y - min_rating] += 1

    hist_a = [0] * size
    hist_b = [0] * size
    for x in a:
        hist_a[x - min_rating] += 1
    for y in b:
        hist_b[y - min_rating] += 1

    num = 0.0
    den = 0.0
    for i in range(size):
        for j in range(size):
            w = ((i - j) ** 2) / ((size - 1) ** 2)
            num += w * observed[i][j]
            den += w * hist_a[i] * hist_b[j] / n
    if den == 0:
        return 1.0
    return round(1 - num / den, 4)


@dataclass
class CalibrationReport:
    n: int
    kappa_nominal: float
    kappa_quadratic: float
    mean_absolute_error: float
    disagreements: list[dict] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.n < 10:
            return 'insufficient_labels'
        if self.kappa_quadratic >= 0.8:
            return 'strong'
        if self.kappa_quadratic >= 0.6:
            return 'moderate'
        if self.kappa_quadratic >= 0.4:
            return 'fair'
        return 'poor'

    def as_dict(self) -> dict:
        return {'n': self.n, 'kappa_nominal': self.kappa_nominal,
                'kappa_quadratic': self.kappa_quadratic,
                'mean_absolute_error': self.mean_absolute_error,
                'verdict': self.verdict, 'disagreements': self.disagreements}


def calibrate(human: dict[str, int], judge: dict[str, int]) -> CalibrationReport:
    """Compare a human score sheet against judge scores on the same cases."""
    shared = sorted(set(human) & set(judge))
    if not shared:
        raise ValueError('no overlapping case ids between human and judge')
    a = [int(round(human[c])) for c in shared]
    b = [int(round(judge[c])) for c in shared]
    disagreements = [{'case_id': c, 'human': x, 'judge': y}
                     for c, x, y in zip(shared, a, b) if x != y]
    return CalibrationReport(
        n=len(shared),
        kappa_nominal=cohen_kappa(a, b),
        kappa_quadratic=quadratic_weighted_kappa(a, b),
        mean_absolute_error=round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 3),
        disagreements=disagreements,
    )


def label_sheet(case_ids: Sequence[str], out_path) -> None:
    """Emit a CSV a human can fill in one column of, without touching code.

    The judge column stays blank until a judge has actually scored the case;
    a sheet with two filled columns is what ``clipbench calibrate`` compares.
    """
    lines = ['case_id,human_score_1to5,judge_score_1to5,note']
    lines += [f'{cid},,,' for cid in case_ids]
    from pathlib import Path
    Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def read_label_sheet(path) -> dict[str, int]:
    from pathlib import Path
    out: dict[str, int] = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines()[1:]:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2 and parts[0] and parts[1]:
            out[parts[0]] = int(float(parts[1]))
    return out
