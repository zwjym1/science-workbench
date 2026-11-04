"""The ReAct loop: plan, act, observe, re-plan.

Design notes worth being able to defend in an interview:

* The loop is a plain state machine over an append-only trace. There is no
  hidden framework behaviour, so "why did it do that" is answered by reading
  one file.
* A failed step is not retried blindly. It is recorded, turned into an
  observation, and the model is asked again -- that *is* the re-plan. Retries
  inside one step exist only for transient environment faults and are capped.
* Tool results are content-addressed on (tool, canonical args). Re-running a
  run whose later steps failed reuses the earlier artefacts instead of paying
  for them twice, and the trace marks each as ``reused`` so a cost comparison
  between two runs stays honest.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget import History, total_tokens
from .llm import Decision, LLMClient
from .tools import ArtifactStore, Tool, ToolContext, ToolError, build_tools
from .trace import Trace

DEFAULT_SYSTEM = (
    'You produce short science explainer videos. Call exactly one tool per turn. '
    'Every factual sentence needs a citation id. Never invent assets, durations '
    'or sources. When the pipeline is done, reply with {"final": "..."} summarising '
    'what was produced and anything that is still unavailable.'
)


@dataclass
class RunResult:
    run_id: str
    status: str                       # ok | failed | exhausted
    final: str = ''
    reason: str = ''
    steps: int = 0
    attempts: int = 0
    reused: int = 0
    artifacts: dict[str, Any] = field(default_factory=dict)
    trace_path: str = ''
    compaction: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0

    def as_dict(self) -> dict:
        return {
            'run_id': self.run_id, 'status': self.status, 'final': self.final,
            'reason': self.reason, 'steps': self.steps, 'attempts': self.attempts,
            'reused_artifacts': self.reused, 'trace_path': self.trace_path,
            'prompt_tokens_estimate': self.prompt_tokens,
            'compactions': self.compaction,
        }


class Agent:
    def __init__(self, client: LLMClient, *, workdir: Path,
                 tools: list[Tool] | None = None,
                 tool_context: ToolContext | None = None,
                 max_steps: int = 12, max_attempts: int = 3,
                 max_tokens: int = 4000, system: str = DEFAULT_SYSTEM):
        self.client = client
        self.workdir = Path(workdir)
        self.tools = {t.name: t for t in (tools or build_tools())}
        self.ctx = tool_context or ToolContext(self.workdir)
        self.max_steps = max_steps
        self.max_attempts = max_attempts
        self.history = History(max_tokens=max_tokens)
        self.store = ArtifactStore(self.workdir / 'artifacts')
        self.system = system

    # -- public ------------------------------------------------------------
    def run(self, task: str, *, run_id: str | None = None) -> RunResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        result = RunResult(run_id=run_id, status='failed')
        trace = Trace(self.workdir / 'runs', run_id)
        result.trace_path = str(trace.path)

        self.history.messages.clear()
        self.history.append('system', self.system)
        self.history.append('user', task)
        trace.record('plan', task=task, tools=sorted(self.tools))

        try:
            for step in range(1, self.max_steps + 1):
                result.steps = step
                compaction = self.history.compact()
                if compaction.saved:
                    trace.record('replan', why='context_compacted',
                                 **compaction.as_dict())
                    result.compaction.append(compaction.as_dict())

                prompt = list(self.history.messages)
                result.prompt_tokens += total_tokens(prompt)
                decision = self.client.decide(prompt, [t.schema() for t in self.tools.values()])
                trace.record('plan', step=step, decision=dict(decision),
                             prompt_tokens=total_tokens(prompt))

                if 'final' in decision:
                    result.status = 'ok'
                    result.final = str(decision['final'])
                    self.history.append('assistant', result.final)
                    trace.record('final', text=result.final)
                    break

                name = str(decision.get('tool', ''))
                args = decision.get('args') or {}
                self.history.append('assistant', f'call {name} {json.dumps(args, ensure_ascii=False)}')

                outcome = self._execute(name, args, trace)
                result.attempts += outcome['attempts']
                result.reused += 1 if outcome.get('reused') else 0
                if outcome['ok']:
                    result.artifacts[name] = outcome['result']
                    self.history.observe(name, json.dumps(outcome['result'], ensure_ascii=False))
                else:
                    # Re-plan: the failure becomes visible input, not a silent retry.
                    self.history.observe(name, f'ERROR {outcome["reason"]}',
                                         error=outcome['reason'])
            else:
                result.status = 'exhausted'
                result.reason = f'max_steps({self.max_steps}) reached without a final answer'
                trace.record('error', step=result.steps, reason=result.reason)
        except Exception as exc:                       # keep the trace readable
            result.status = 'failed'
            result.reason = f'{type(exc).__name__}: {exc}'
            trace.record('error', reason=result.reason)
        finally:
            trace.close()
        return result

    # -- internals ---------------------------------------------------------
    def _execute(self, name: str, args: dict, trace: Trace) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            reason = f'unknown_tool:{name}'
            trace.record('error', tool=name, reason=reason)
            return {'ok': False, 'reason': reason, 'attempts': 0}

        cached = self.store.load(name, args)
        if cached is not None:
            trace.record('tool', tool=name, args=args, reused=True,
                         result_status=cached.get('status'))
            return {'ok': True, 'result': cached, 'attempts': 0, 'reused': True}

        last = ''
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = tool.fn(args, self.ctx)
            except ToolError as exc:
                last = f'invalid_arguments: {exc}'
                trace.record('error', tool=name, attempt=attempt, reason=last)
                continue                              # bad args do not fix themselves
            except Exception as exc:
                last = f'{type(exc).__name__}: {exc}'
                trace.record('error', tool=name, attempt=attempt, reason=last)
                continue
            saved = self.store.save(name, args, payload)
            trace.record('tool', tool=name, args=args, attempt=attempt,
                         result_status=payload.get('status'), reused=False)
            return {'ok': True, 'result': saved, 'attempts': attempt}
        return {'ok': False, 'reason': last or 'unknown_failure', 'attempts': self.max_attempts}
