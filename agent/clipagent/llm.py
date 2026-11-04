"""Model clients.

The loop only needs one method, so the harness stays testable without a vendor
SDK. ``ScriptedClient`` replays a fixed list of decisions and is what the tests
use; ``OpenAICompatClient`` speaks the common /chat/completions shape and is
inert unless an endpoint and key are configured.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class Decision(dict):
    """Either {"tool": name, "args": {...}} or {"final": text}."""


class LLMClient(Protocol):
    def decide(self, messages: list[dict], tools: list[dict]) -> Decision: ...


class ScriptedClient:
    """Deterministic stand-in. Raises if the script runs out, so a test cannot
    accidentally pass by looping forever."""

    def __init__(self, decisions: list[dict], *, record: bool = False):
        self.decisions = list(decisions)
        self.calls: list[dict[str, Any]] = []
        self.record = record

    def decide(self, messages: list[dict], tools: list[dict]) -> Decision:
        if self.record:
            self.calls.append({'messages': list(messages), 'tools': list(tools)})
        if not self.decisions:
            raise RuntimeError('ScriptedClient exhausted: the loop asked for more '
                               'decisions than the script provides')
        return Decision(self.decisions.pop(0))


@dataclass
class OpenAICompatClient:
    """Minimal function-calling client for any OpenAI-compatible endpoint."""

    base_url: str
    model: str
    api_key: str = ''
    temperature: float = 0.0
    timeout: int = 60

    @classmethod
    def from_env(cls) -> 'OpenAICompatClient | None':
        base = os.environ.get('CLIPAGENT_BASE_URL')
        model = os.environ.get('CLIPAGENT_MODEL')
        if not base or not model:
            return None
        return cls(base_url=base.rstrip('/'), model=model,
                   api_key=os.environ.get('CLIPAGENT_API_KEY', ''))

    def decide(self, messages: list[dict], tools: list[dict]) -> Decision:
        body = {'model': self.model, 'messages': _to_chat(messages),
                'temperature': self.temperature}
        if tools:
            body['tools'] = tools
            body['tool_choice'] = 'auto'
        request = urllib.request.Request(
            self.base_url + '/chat/completions',
            data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Authorization': f'Bearer {self.api_key}'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(f'model endpoint unreachable: {exc}') from exc

        message = payload['choices'][0]['message']
        calls = message.get('tool_calls') or []
        if calls:
            call = calls[0]
            try:
                args = json.loads(call['function'].get('arguments') or '{}')
            except json.JSONDecodeError as exc:
                raise RuntimeError(f'model returned non-JSON arguments: {exc}') from exc
            return Decision({'tool': call['function']['name'], 'args': args})
        return Decision({'final': message.get('content') or ''})


def _to_chat(messages: list[dict]) -> list[dict]:
    """Flatten the harness history into plain chat turns."""
    out = []
    for message in messages:
        role = message['role']
        if role == 'observation':
            tool = (message.get('meta') or {}).get('tool', 'tool')
            out.append({'role': 'user',
                        'content': f'[observation from {tool}]\n{message["content"]}'})
        elif role == 'summary':
            out.append({'role': 'system', 'content': message['content']})
        else:
            out.append({'role': role, 'content': message['content']})
    return out
