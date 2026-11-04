"""Token budget and history compaction.

Token counts are estimates: CJK characters cost roughly one token each and
ASCII about a quarter, which is close enough for a budget guard and keeps the
harness free of a tokenizer dependency. The numbers are labelled as estimates
wherever they are reported, because a budget that silently claims precision is
worse than one that admits it is approximate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    wide = sum(1 for ch in text if ord(ch) > 0x2E7F)
    narrow = len(text) - wide
    return wide + math.ceil(narrow / 4)


def total_tokens(messages: Iterable[dict]) -> int:
    return sum(estimate_tokens(m.get('content', '')) for m in messages)


@dataclass
class CompactionReport:
    before: int
    after: int
    dropped: int = 0
    summarized: int = 0
    tools_dropped: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return self.before - self.after

    def as_dict(self) -> dict:
        return {
            'before_estimate': self.before,
            'after_estimate': self.after,
            'dropped_messages': self.dropped,
            'summarized_observations': self.summarized,
            'tools_in_summary': list(self.tools_dropped),
            'note': 'token counts are character-based estimates, not tokenizer output',
        }


class History:
    """Conversation history with a hard ceiling on estimated size."""

    def __init__(self, max_tokens: int = 4000, keep_recent: int = 6):
        if max_tokens <= 0:
            raise ValueError('max_tokens must be positive')
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.messages: list[dict] = []

    def append(self, role: str, content: str, **meta) -> dict:
        msg = {'role': role, 'content': content}
        if meta:
            msg['meta'] = meta
        self.messages.append(msg)
        return msg

    def observe(self, tool: str, content: str, **meta) -> dict:
        return self.append('observation', content, tool=tool, **meta)

    def compact(self) -> CompactionReport:
        """Keep the two anchors and the newest turns; summarise the rest."""
        before = total_tokens(self.messages)
        if before <= self.max_tokens or len(self.messages) <= 2 + self.keep_recent:
            return CompactionReport(before=before, after=before)

        head = self.messages[:1]          # system prompt
        goal = self.messages[1:2]         # original task
        body = self.messages[2:]
        recent = body[-self.keep_recent:]
        dropped = body[:-self.keep_recent]

        tools: list[str] = []
        for m in dropped:
            tool = (m.get('meta') or {}).get('tool')
            if tool and tool not in tools:
                tools.append(tool)
        summary_text = (f'[compacted] {len(dropped)} earlier steps removed '
                        f'({total_tokens(dropped)} estimated tokens); '
                        f'tools involved: {", ".join(tools) or "none"}')
        summary = {'role': 'summary', 'content': summary_text,
                   'meta': {'compacted': len(dropped), 'tools': tools}}

        self.messages = head + goal + [summary] + recent
        after = total_tokens(self.messages)
        return CompactionReport(before=before, after=after, dropped=len(dropped),
                                summarized=len(dropped), tools_dropped=tools)
