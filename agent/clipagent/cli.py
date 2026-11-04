"""Command line entry point.

``clipagent demo`` runs the harness against a fixed script so the pipeline can be
inspected without a model key. ``clipagent run`` uses whatever OpenAI-compatible
endpoint the environment provides.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .llm import OpenAICompatClient, ScriptedClient
from .loop import Agent
from .tools import ToolContext


DEMO_TASK = ('做一条 40 秒的科普短视频，讲水循环，必须引用来源，'
             '至少 4 个镜头，最后报告渲染结果。')

DEMO_SCRIPT = [
    {'tool': 'search_assets', 'args': {'query': 'water', 'limit': 3}},
    {'tool': 'write_script', 'args': {
        'topic': '水循环', 'duration_s': 40,
        'citations': ['IPCC AR6 WG1 ch8', 'USGS water cycle']}},
    {'tool': 'make_storyboard', 'args': {
        'sentences': [
            {'text': '水循环：现象。', 'citation': 'IPCC AR6 WG1 ch8'},
            {'text': '水循环：机制。', 'citation': 'USGS water cycle'},
            {'text': '水循环：证据。', 'citation': 'IPCC AR6 WG1 ch8'},
            {'text': '水循环：边界。', 'citation': 'USGS water cycle'}],
        'shots': 4, 'asset_ids': ['a01', 'a02'], 'duration_s': 40}},
    {'tool': 'synthesize_tts', 'args': {'shots': [
        {'index': 0, 'seconds': 10.0}, {'index': 1, 'seconds': 10.0},
        {'index': 2, 'seconds': 10.0}, {'index': 3, 'seconds': 10.0}]}},
    {'tool': 'render_and_check', 'args': {'shots': [
        {'index': 0, 'seconds': 10.0}, {'index': 1, 'seconds': 10.0},
        {'index': 2, 'seconds': 10.0}, {'index': 3, 'seconds': 10.0}]}},
    {'final': '已完成 4 镜头预览渲染；配音轨为占位静音，未配置语音引擎。'},
]


def _run(task: str, workdir: Path, client, max_steps: int) -> int:
    agent = Agent(client, workdir=workdir,
                  tool_context=ToolContext(workdir), max_steps=max_steps)
    result = agent.run(task)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    for name, payload in result.artifacts.items():
        status = payload.get('status')
        print(f'  {name}: status={status} reused={payload.get("reused")}')
    return 0 if result.status == 'ok' else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='clipagent', description=__doc__)
    parser.add_argument('mode', choices=['demo', 'run'])
    parser.add_argument('task', nargs='?', default=DEMO_TASK)
    parser.add_argument('--workdir', type=Path, default=None)
    parser.add_argument('--max-steps', type=int, default=12)
    args = parser.parse_args(argv)

    workdir = args.workdir or Path(tempfile.mkdtemp(prefix='clipagent-'))
    workdir.mkdir(parents=True, exist_ok=True)

    if args.mode == 'demo':
        return _run(args.task, workdir, ScriptedClient(list(DEMO_SCRIPT)), args.max_steps)

    client = OpenAICompatClient.from_env()
    if client is None:
        print('set CLIPAGENT_BASE_URL and CLIPAGENT_MODEL to run against a model',
              file=sys.stderr)
        return 2
    return _run(args.task, workdir, client, args.max_steps)


if __name__ == '__main__':
    raise SystemExit(main())
