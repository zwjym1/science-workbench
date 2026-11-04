"""The same pipeline expressed with LangChain, for comparison rather than use.

The point of this file is to have an answer when someone asks "have you used a
framework?". It is not vendored into the main path because the loop is 150 lines
and the framework adds a dependency and a layer of indirection; that trade-off is
the interesting part of the comparison, so it is recorded here instead of hidden.

Import is lazy so the harness and its tests run with no third-party packages.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .tools import Tool, ToolContext, build_tools


def available() -> bool:
    try:
        import langchain_core  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class ParityReport:
    only_native: list[str]
    only_framework: list[str]
    schema_mismatch: list[str]

    @property
    def ok(self) -> bool:
        return not (self.only_native or self.only_framework or self.schema_mismatch)

    def as_dict(self) -> dict:
        return {'ok': self.ok, 'only_native': self.only_native,
                'only_framework': self.only_framework,
                'schema_mismatch': self.schema_mismatch}


_TYPE_MAP = {'string': str, 'integer': int, 'number': float,
             'boolean': bool, 'array': list, 'object': dict}


def _args_model(tool: Tool):
    """Rebuild the JSON schema as a pydantic model.

    Passing ``**kwargs`` alone makes the framework advertise a single ``kwargs``
    parameter, so the model would never learn the real argument names. The parity
    check exists to catch exactly that.
    """
    from pydantic import Field, create_model

    properties = tool.parameters.get('properties', {}) or {}
    required = set(tool.parameters.get('required', []) or [])
    fields = {}
    for name, spec in properties.items():
        annotation = _TYPE_MAP.get(spec.get('type', 'string'), str)
        default = ... if name in required else None
        fields[name] = (annotation, Field(default, description=spec.get('description', '')))
    return create_model(f'{tool.name}_args', **fields)


def build_langchain_tools(ctx: ToolContext, tools: list[Tool] | None = None):
    """Expose the identical five tools as LangChain StructuredTool objects."""
    from langchain_core.tools import StructuredTool

    built = []
    for tool in (tools or build_tools()):
        def runner(_tool=tool, **kwargs):
            return json.dumps(_tool.fn(kwargs, ctx), ensure_ascii=False)

        built.append(StructuredTool.from_function(
            func=runner, name=tool.name, description=tool.description,
            args_schema=_args_model(tool)))
    return built


def build_executor(model: Any, ctx: ToolContext, *, verbose: bool = False):
    """Create a tool-calling agent executor over the same tool set."""
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_messages([
        ('system', 'You produce short science explainer videos. '
                   'Every factual sentence needs a citation id.'),
        ('human', '{input}'),
        ('placeholder', '{agent_scratchpad}'),
    ])
    agent = create_tool_calling_agent(model, build_langchain_tools(ctx), prompt)
    return AgentExecutor(agent=agent, tools=build_langchain_tools(ctx), verbose=verbose)


def parity_report(tools: list[Tool] | None = None) -> ParityReport:
    """Compare the native registry against what the framework exposes."""
    native = {t.name: t for t in (tools or build_tools())}
    if not available():
        return ParityReport(only_native=sorted(native), only_framework=[],
                            schema_mismatch=[])
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        framework = {}
        for tool in build_langchain_tools(ToolContext('.'), list(native.values())):
            framework[tool.name] = convert_to_openai_tool(tool)
    except Exception as exc:  # pragma: no cover - depends on installed version
        return ParityReport(only_native=[], only_framework=[],
                            schema_mismatch=[f'framework introspection failed: {exc}'])

    mismatch = []
    for name, tool in native.items():
        other = framework.get(name)
        if not other:
            continue
        want = set(tool.parameters.get('properties', {}))
        got = set((other.get('function', {}).get('parameters', {})
                   .get('properties', {})))
        if want != got:
            mismatch.append(f'{name}: native={sorted(want)} framework={sorted(got)}')
    return ParityReport(only_native=sorted(set(native) - set(framework)),
                        only_framework=sorted(set(framework) - set(native)),
                        schema_mismatch=mismatch)
