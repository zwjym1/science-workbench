"""A reference policy, not a model.

It turns a case's declared constraints into a fixed tool sequence. That makes the
runner, the metrics and the reports testable end to end without an API key, and
it is labelled as a stand-in everywhere it appears: results produced with it say
something about the harness, never about a model's capability.
"""
from __future__ import annotations

from .case import Case

LABEL = 'scripted-reference-policy (runner mechanics only; not a model measurement)'


def build(case: Case) -> list[dict]:
    constraints = case.constraints
    shots = int(constraints.get('shots', 3))
    duration = int(constraints.get('duration_s', 30))
    steps: list[dict] = [
        {'tool': 'search_assets', 'args': {'query': case.title, 'limit': 5}},
    ]

    if case.known_failure:
        # Deliberately omits citations: the tool must refuse, and the policy
        # reports that it stopped instead of inventing a source.
        steps.append({'tool': 'write_script',
                      'args': {'topic': case.title, 'duration_s': max(duration, 15)}})
        steps.append({'final': '没有可靠来源，按约束停止，不编造引用。'})
        return steps

    steps.append({'tool': 'write_script',
                  'args': {'topic': case.title, 'duration_s': max(duration, 15),
                           'citations': ['IPCC AR6 WG1', 'USGS']}})
    steps.append({'tool': 'make_storyboard',
                  'args': {'sentences': [{'text': f'{case.title}：{i}。',
                                          'citation': 'IPCC AR6 WG1'}
                                         for i in range(min(shots, 4))],
                           'shots': shots, 'asset_ids': ['a01', 'a02', 'a03'],
                           'duration_s': duration}})
    if 'audio-optional' not in case.tags:
        steps.append({'tool': 'synthesize_tts',
                      'args': {'shots': [{'index': i, 'seconds': duration / shots}
                                         for i in range(shots)]}})
    if constraints.get('render'):
        steps.append({'tool': 'render_and_check',
                      'args': {'shots': [{'index': i, 'seconds': duration / shots}
                                         for i in range(shots)]}})
    steps.append({'final': '完成；配音为占位静音时状态已如实标注。'})
    return steps
