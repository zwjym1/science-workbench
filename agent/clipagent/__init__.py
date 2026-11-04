"""ReAct agent harness for a short science-explainer pipeline.

Public surface: :class:`Agent`, :func:`build_tools`, :class:`ScriptedClient`.
"""

from .budget import History, estimate_tokens
from .llm import Decision, OpenAICompatClient, ScriptedClient
from .loop import Agent, RunResult
from .tools import Tool, ToolContext, ToolError, build_tools
from .trace import Trace

__all__ = [
    'Agent', 'RunResult', 'Tool', 'ToolContext', 'ToolError', 'Trace',
    'History', 'estimate_tokens', 'Decision', 'ScriptedClient',
    'OpenAICompatClient', 'build_tools',
]
__version__ = '0.1.0'
