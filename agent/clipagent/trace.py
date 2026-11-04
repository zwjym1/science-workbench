"""Append-only run traces.

One JSON object per line, flushed as it happens, so a killed run still leaves a
readable prefix. Every entry carries ``seq`` and ``run_id``; nothing is rewritten
in place, which is what makes the failure-attribution report trustworthy later.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class Step:
    seq: int
    kind: str                      # plan | tool | observation | replan | final | error
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Trace:
    def __init__(self, run_dir: Path, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / f'{self.run_id}.jsonl'
        self._seq = 0
        self._fh = self.path.open('a', encoding='utf-8', newline='\n')

    def record(self, kind: str, **payload: Any) -> Step:
        self._seq += 1
        step = Step(seq=self._seq, kind=kind, payload=payload)
        self._fh.write(json.dumps({'run_id': self.run_id, **step.as_dict()},
                                  ensure_ascii=False) + '\n')
        self._fh.flush()
        os.fsync(self._fh.fileno())
        return step

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> 'Trace':
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- readers -----------------------------------------------------------
    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        rows = []
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
