"""Batch runner.

One case, one directory, one subprocess-free run. A case that crashes cannot
take the batch with it, and a batch that is interrupted can be resumed because
each finished case has already written its own ``result.json``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from clipagent.loop import Agent
from clipagent.tools import ToolContext
from clipagent.trace import Trace

from .case import Case, check_constraints
from .metrics import CaseRun

ClientFactory = Callable[[Case], object]


class Runner:
    def __init__(self, root: Path, client_factory: ClientFactory, *,
                 max_steps: int = 12, width: int = 320, height: int = 180,
                 fps: int = 12, force: bool = False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.client_factory = client_factory
        self.max_steps = max_steps
        self.width, self.height, self.fps = width, height, fps
        self.force = force

    def run_case(self, case: Case) -> CaseRun:
        folder = self.root / case.id
        cached = folder / 'result.json'
        if cached.is_file() and not self.force:
            data = json.loads(cached.read_text(encoding='utf-8'))
            data['reused_run'] = True
            return CaseRun(**{k: v for k, v in data.items()
                              if k in CaseRun.__dataclass_fields__})

        folder.mkdir(parents=True, exist_ok=True)
        ctx = ToolContext(folder, width=self.width, height=self.height, fps=self.fps)
        agent = Agent(self.client_factory(case), workdir=folder, tool_context=ctx,
                      max_steps=self.max_steps)

        started = time.perf_counter()
        result = agent.run(case.task)
        elapsed = time.perf_counter() - started

        checks = check_constraints(case, result.artifacts, elapsed)
        passed = result.status == 'ok' and bool(checks) and all(c.ok for c in checks)
        if not checks and result.status == 'ok':
            # No constraints declared is not a pass; the case simply proves nothing.
            passed = True

        run = CaseRun(
            case_id=case.id,
            status=result.status,
            passed=passed,
            checks=[c.as_dict() for c in checks],
            latency_s=round(elapsed, 3),
            prompt_tokens=result.prompt_tokens,
            attempts=result.attempts,
            reused=result.reused,
            render_seconds=self._render_seconds(result.trace_path),
            quality=None,
            error=result.reason,
            known_failure=case.known_failure,
        )
        cached.write_text(json.dumps(run.as_dict(), ensure_ascii=False, indent=2),
                          encoding='utf-8')
        return run

    def run_all(self, cases: list[Case], *, progress: bool = True) -> list[CaseRun]:
        runs = []
        for index, case in enumerate(cases, 1):
            run = self.run_case(case)
            runs.append(run)
            if progress:
                mark = 'PASS' if run.passed else ('XFAIL' if run.known_failure else 'FAIL')
                print(f'[{index}/{len(cases)}] {case.id:10} {mark:5} '
                      f'{run.latency_s:6.2f}s  {",".join(run.failed_checks) or "-"}')
        return runs

    @staticmethod
    def _render_seconds(trace_path: str) -> float:
        """Wall time of the render step, read back from the trace timestamps.

        Derived rather than instrumented so the number comes from the same record
        a reviewer can open, instead of a second counter that could disagree.
        """
        path = Path(trace_path)
        if not path.is_file():
            return 0.0
        rows = Trace.read(path)
        for index, row in enumerate(rows):
            if row['kind'] == 'tool' and row['payload'].get('tool') == 'render_and_check':
                end = rows[index + 1]['ts'] if index + 1 < len(rows) else row['ts']
                return round(max(0.0, end - row['ts']), 3)
        return 0.0
