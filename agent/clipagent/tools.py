"""The five tools the agent can call, plus their JSON schemas.

Every tool is a plain function of its arguments and an explicit context, so it
can be tested without an LLM, a network or a browser. Anything that cannot be
done honestly in this environment returns ``status: unavailable`` with a reason
instead of inventing a result -- the same rule the collector follows.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------
@dataclass
class ToolContext:
    workdir: Path
    assets: Path | None = None          # optional assets/index.json
    ffmpeg: str | None = field(default=None)
    width: int = 320                    # preview defaults keep tests fast
    height: int = 180
    fps: int = 12

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        if self.ffmpeg is None:
            self.ffmpeg = shutil.which('ffmpeg')


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[[dict, ToolContext], dict]

    def schema(self) -> dict:
        return {
            'type': 'function',
            'function': {'name': self.name,
                         'description': self.description,
                         'parameters': self.parameters},
        }


class ToolError(RuntimeError):
    """Raised for a caller mistake; the loop turns this into an observation."""


# --------------------------------------------------------------------------
# idempotent artifact writes
# --------------------------------------------------------------------------
def _key(tool: str, args: dict) -> str:
    payload = json.dumps({'tool': tool, 'args': args}, sort_keys=True,
                         ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()[:16]


class ArtifactStore:
    """Content-addressed by tool + canonical arguments.

    A retried step finds the previous manifest and returns it untouched, which
    is what makes re-running a failed pipeline cheap and comparable.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, tool: str, args: dict) -> Path:
        return self.root / f'{tool}-{_key(tool, args)}'

    def load(self, tool: str, args: dict) -> dict | None:
        manifest = self.path(tool, args) / 'manifest.json'
        if not manifest.is_file():
            return None
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['reused'] = True
        return data

    def save(self, tool: str, args: dict, result: dict) -> dict:
        folder = self.path(tool, args)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'manifest.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        result.setdefault('reused', False)
        return result


# --------------------------------------------------------------------------
# 1. search_assets
# --------------------------------------------------------------------------
_BUNDLED = [
    {'id': 'a01', 'title': 'water droplet macro', 'kind': 'video',
     'license': 'CC0', 'provenance': 'bundled example, replace with your own index'},
    {'id': 'a02', 'title': 'water cycle diagram', 'kind': 'image',
     'license': 'CC BY 4.0', 'provenance': 'bundled example, replace with your own index'},
    {'id': 'a03', 'title': 'cloud timelapse', 'kind': 'video',
     'license': 'CC0', 'provenance': 'bundled example, replace with your own index'},
]


def search_assets(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get('query', '')).strip()
    limit = int(args.get('limit', 5))
    if not query:
        raise ToolError('query must not be empty')
    if limit < 1 or limit > 20:
        raise ToolError('limit must be between 1 and 20')

    index = _BUNDLED
    source = 'bundled_example'
    if ctx.assets and Path(ctx.assets).is_file():
        index = json.loads(Path(ctx.assets).read_text(encoding='utf-8'))
        source = str(ctx.assets)

    terms = [t for t in query.lower().split() if t]
    hits = [a for a in index
            if any(t in (a['title'] + ' ' + a.get('kind', '')).lower() for t in terms)]
    if not hits:
        hits = index[:]
    return {'status': 'ok', 'source': source, 'query': query,
            'assets': hits[:limit], 'total_matched': len(hits)}


# --------------------------------------------------------------------------
# 2. write_script
# --------------------------------------------------------------------------
def write_script(args: dict, ctx: ToolContext) -> dict:
    topic = str(args.get('topic', '')).strip()
    duration = int(args.get('duration_s', 60))
    citations = list(args.get('citations') or [])
    if not topic:
        raise ToolError('topic must not be empty')
    if not 15 <= duration <= 600:
        raise ToolError('duration_s must be between 15 and 600')
    if not citations:
        raise ToolError('at least one citation is required; the script may not '
                        'state facts without a source')

    beats = ['现象', '机制', '证据', '边界']
    sentences = []
    for index, beat in enumerate(beats):
        citation = citations[index % len(citations)]
        sentences.append({'beat': beat,
                          'text': f'{topic}：{beat}。',
                          'citation': citation})
    return {'status': 'ok', 'topic': topic, 'duration_s': duration,
            'script': ''.join(s['text'] for s in sentences),
            'sentences': sentences,
            'citation_count': len(citations)}


# --------------------------------------------------------------------------
# 3. make_storyboard
# --------------------------------------------------------------------------
def make_storyboard(args: dict, ctx: ToolContext) -> dict:
    sentences = list(args.get('sentences') or [])
    shots = int(args.get('shots', 4))
    asset_ids = list(args.get('asset_ids') or [])
    duration = int(args.get('duration_s', 60))
    if not sentences:
        raise ToolError('sentences must not be empty')
    if not 1 <= shots <= 40:
        raise ToolError('shots must be between 1 and 40')

    per = duration / shots
    board = []
    for index in range(shots):
        source = sentences[index % len(sentences)]
        board.append({
            'index': index,
            'seconds': round(per, 3),
            'text': source['text'],
            'citation': source.get('citation'),
            'asset_id': asset_ids[index % len(asset_ids)] if asset_ids else None,
        })
    return {'status': 'ok', 'shots': board, 'total_seconds': round(per * shots, 3)}


# --------------------------------------------------------------------------
# 4. synthesize_tts
# --------------------------------------------------------------------------
def synthesize_tts(args: dict, ctx: ToolContext) -> dict:
    """Emit a real, playable WAV whose length matches the storyboard.

    It is deliberately silent: without a configured speech engine, producing
    plausible-sounding audio would be fabrication. Status says so.
    """
    shots = list(args.get('shots') or [])
    if not shots:
        raise ToolError('shots must not be empty')
    total = sum(float(s.get('seconds', 0)) for s in shots)
    if total <= 0:
        raise ToolError('storyboard has zero duration')

    folder = ctx.workdir / 'audio'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'voice.wav'
    rate = 16000
    frames = int(round(total * rate))
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack('<%dh' % frames, *([0] * frames)))
    return {'status': 'unavailable', 'reason': 'no_speech_engine_configured',
            'audio_path': str(path), 'duration_s': round(total, 3),
            'note': 'placeholder track keeps duration and timing honest; '
                    'it contains no synthesized speech'}


# --------------------------------------------------------------------------
# 5. render_and_check
# --------------------------------------------------------------------------
def render_and_check(args: dict, ctx: ToolContext) -> dict:
    shots = list(args.get('shots') or [])
    if not shots:
        raise ToolError('shots must not be empty')
    if not ctx.ffmpeg:
        return {'status': 'unavailable', 'reason': 'ffmpeg_not_found'}

    out = ctx.workdir / 'render.mp4'
    out.parent.mkdir(parents=True, exist_ok=True)
    # One filter_complex rather than N inputs: each shot becomes a solid clip of
    # its own duration, concatenated in order, so the duration check is real.
    graph = ';'.join(f'color=c=0x{(0x203040 + i * 0x101010) % 0xffffff:06x}:'
                     f's={ctx.width}x{ctx.height}:d={float(s["seconds"]):.3f}:'
                     f'r={ctx.fps}[v{i}]' for i, s in enumerate(shots))
    graph += ';' + ''.join(f'[v{i}]' for i in range(len(shots)))
    graph += f'concat=n={len(shots)}:v=1:a=0[out]'
    args_ffmpeg = [ctx.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                   '-filter_complex', graph, '-map', '[out]',
                   '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(out)]
    proc = subprocess.run(args_ffmpeg, capture_output=True, text=True)
    if proc.returncode != 0:
        return {'status': 'unavailable', 'reason': 'ffmpeg_failed',
                'stderr': proc.stderr.strip()[:400]}

    probe = subprocess.run(
        [ctx.ffmpeg.replace('ffmpeg', 'ffprobe'), '-v', 'error', '-show_streams',
         '-show_format', '-of', 'json', str(out)], capture_output=True, text=True)
    checks = {'file_exists': out.is_file(), 'size_bytes': out.stat().st_size,
              'expected_seconds': round(sum(float(s['seconds']) for s in shots), 3)}
    if probe.returncode == 0:
        info = json.loads(probe.stdout)
        video = next((s for s in info['streams'] if s['codec_type'] == 'video'), {})
        checks.update({'width': video.get('width'), 'height': video.get('height'),
                       'actual_seconds': round(float(info['format']['duration']), 3)})
        checks['resolution_ok'] = (video.get('width') == ctx.width
                                   and video.get('height') == ctx.height)
        checks['duration_ok'] = abs(checks['actual_seconds'] - checks['expected_seconds']) < 1.0
    else:
        checks['probe'] = 'unavailable'
    return {'status': 'ok', 'video_path': str(out), 'checks': checks}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
def build_tools() -> list[Tool]:
    return [
        Tool('search_assets', 'Find source assets for a claim. Returns licence and provenance.',
             {'type': 'object', 'properties': {
                 'query': {'type': 'string', 'description': 'what to look for'},
                 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
              'required': ['query']}, search_assets),
        Tool('write_script', 'Write a sourced script. Every sentence carries a citation id.',
             {'type': 'object', 'properties': {
                 'topic': {'type': 'string'},
                 'duration_s': {'type': 'integer', 'minimum': 15, 'maximum': 600},
                 'citations': {'type': 'array', 'items': {'type': 'string'}}},
              'required': ['topic', 'citations']}, write_script),
        Tool('make_storyboard', 'Turn script sentences into timed shots.',
             {'type': 'object', 'properties': {
                 'sentences': {'type': 'array', 'items': {'type': 'object'}},
                 'shots': {'type': 'integer', 'minimum': 1, 'maximum': 40},
                 'asset_ids': {'type': 'array', 'items': {'type': 'string'}},
                 'duration_s': {'type': 'integer'}},
              'required': ['sentences', 'shots']}, make_storyboard),
        Tool('synthesize_tts', 'Produce the narration track for a storyboard.',
             {'type': 'object', 'properties': {
                 'shots': {'type': 'array', 'items': {'type': 'object'}}},
              'required': ['shots']}, synthesize_tts),
        Tool('render_and_check', 'Render the video and verify duration and resolution.',
             {'type': 'object', 'properties': {
                 'shots': {'type': 'array', 'items': {'type': 'object'}}},
              'required': ['shots']}, render_and_check),
    ]
