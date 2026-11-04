"""Optional content extraction using the current guest context and local tools only."""
import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit


MAX_MEDIA_BYTES = 150_000_000
MAX_SUBTITLE_BYTES = 2_000_000
OFFICIAL_HOSTS = ('douyinvod.com', 'douyin.com', 'douyinstatic.com', 'douyinpic.com')


def _safe_text(value):
    text = str(value)
    text = re.sub(r'https?://\S+', '[redacted_url]', text, flags=re.I)
    return re.sub(r'(?i)(?:cookie|authorization)\s*[:=][^\r\n]*', '[redacted_secret]', text)


async def _official_url(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not any(host == domain or host.endswith('.' + domain) for domain in OFFICIAL_HOSTS)):
            return False
        addresses = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM), timeout=10)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (ValueError, OSError, TypeError, TimeoutError):
        return False


async def _fetch(context, url, limit, timeout, media=False):
    """Single normal request. Range limits cooperative servers; Playwright buffers bodies."""
    if not isinstance(url, str) or not await _official_url(url):
        return {'status': 'blocked', 'reason': 'unsafe_url'}, None
    response = None
    try:
        response = await context.request.get(
            url, timeout=timeout, max_redirects=0, max_retries=0,
            headers={'Range': f'bytes=0-{limit}'})
        status = response.status
        if status not in (200, 206):
            return {'status': 'blocked', 'reason': 'http_rejected', 'http_status': status}, None
        headers = {k.lower(): v for k, v in response.headers.items()}
        length = headers.get('content-length')
        total = headers.get('content-range', '').rsplit('/', 1)[-1]
        if ((length and int(length) > limit) or (total.isdigit() and int(total) > limit)):
            return {'status': 'blocked', 'reason': 'size_limit'}, None
        content_type = headers.get('content-type', '').split(';')[0].lower()
        if media and not (content_type.startswith('video/') or content_type == 'application/octet-stream'):
            return {'status': 'blocked', 'reason': 'unexpected_content_type'}, None
        data = await response.body()
        if len(data) > limit:
            return {'status': 'blocked', 'reason': 'size_limit'}, None
        return {'status': 'available', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}, data
    except Exception as exc:
        # Never expose exception messages: transport errors often contain signed URLs.
        return {'status': 'blocked', 'reason': 'request_failed', 'error_type': type(exc).__name__}, None
    finally:
        if response is not None:
            try:
                await response.dispose()
            except Exception:
                pass


def _probe(path):
    try:
        process = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                                  '-of', 'json', str(path)], capture_output=True, text=True,
                                 timeout=20, check=True, shell=False)
        info = json.loads(process.stdout)
        return {'has_audio': any(s.get('codec_type') == 'audio' for s in info.get('streams', [])),
                'duration_seconds': float(info.get('format', {}).get('duration', 0))}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {'probe_status': 'unavailable'}


def _segments(data):
    """Parse captured JSON subtitle records or SRT/WebVTT without generated prose."""
    text = data.decode('utf-8-sig')
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    segments = []
    if parsed is not None:
        items = parsed if isinstance(parsed, list) else parsed.get('utterances', parsed.get('segments', []))
        for item in items:
            # Douyin utterances carry milliseconds; normalized segments carry seconds.
            divisor = 1000 if 'start_time' in item else 1
            start = float(item.get('start_time', item.get('start', 0))) / divisor
            end = float(item.get('end_time', item.get('end', start))) / divisor
            if end >= start >= 0 and str(item.get('text', '')).strip():
                segments.append({'start': start, 'end': end, 'text': _safe_text(item['text'])[:4000]})
    else:
        def seconds(value):
            parts = value.replace(',', '.').split(':')
            return sum(float(v) * 60 ** i for i, v in enumerate(reversed(parts)))
        pattern = r'((?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
        for match in re.finditer(pattern, text, flags=re.S):
            start, end = seconds(match[1]), seconds(match[2])
            if end >= start >= 0:
                segments.append({'start': start, 'end': end, 'text': _safe_text(match[3].strip())[:4000]})
    return segments[:500]


def _write_artifact(output_dir, name, data):
    output_dir.mkdir(parents=True, exist_ok=True)
    # A fresh name preserves previous collection evidence, including refreshes.
    path = output_dir / f'{uuid.uuid4().hex}-{name}'
    path.write_bytes(data)
    return path


def _subtitle_source(detail, video):
    for index, sticker in enumerate(detail.get('interaction_stickers') or []):
        for caption_index, caption in enumerate((sticker.get('auto_video_caption_info') or {}).get('auto_captions') or []):
            url = caption.get('url') or {}
            urls = (url.get('url_list') or []) if isinstance(url, dict) else [url]
            if urls:
                return urls[0], f'interaction_stickers[{index}].auto_video_caption_info.auto_captions[{caption_index}]'
    for index, caption in enumerate((video.get('cla_info') or {}).get('caption_infos') or []):
        if caption.get('url'):
            return caption['url'], f'video.cla_info.caption_infos[{index}]'
    for owner, prefix in ((video, 'video.subtitle_infos'), (detail, 'subtitle_infos')):
        subtitles = owner.get('subtitle_infos') or []
        if subtitles:
            subtitle = subtitles[0]
            url = subtitle.get('url') or (subtitle.get('url_list') or [None])[0]
            return url, prefix + '[0]'
    return None, None


def _local_asr(media, output_dir, metadata):
    if metadata.get('has_audio') is False:
        return {'status': 'needs_review', 'reason': 'no_audio', 'segments': []}
    if 'has_audio' not in metadata:
        return {'status': 'unavailable', 'reason': 'audio_probe_unavailable'}
    script = Path(__file__).resolve().parents[2] / 'research/douyin-validation/transcribe_local.py'
    if not script.is_file():
        return {'status': 'unavailable', 'reason': 'local_asr_unavailable'}
    asr_dir = output_dir / ('asr-' + uuid.uuid4().hex)
    # Shared across jobs; fixed script, model and argv, never a user supplied command.
    cache = Path.home() / '.cache' / 'dycollector' / 'asr-models'
    try:
        subprocess.run([sys.executable, str(script), str(media), '--model', 'small',
                        '--output-dir', str(asr_dir), '--model-cache-root', str(cache)],
                       shell=False, capture_output=True, timeout=1800, check=True)
        data = json.loads((asr_dir / 'transcript.json').read_text(encoding='utf-8'))
        segments = _segments(json.dumps(data).encode('utf-8'))
        duration = max(float(data.get('media_duration_seconds', 0)), .001)
        coverage = min(1, sum(s['end'] - s['start'] for s in segments) / duration)
        reason = 'no_speech' if not segments else ('low_coverage' if coverage < .15 else 'machine_transcript_unreviewed')
        return {'status': 'needs_review', 'reason': reason, 'segments': segments,
                'coverage': coverage, 'source_path': 'local_asr',
                'artifact_path': str((asr_dir / 'transcript.json').relative_to(output_dir))}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        return {'status': 'unavailable', 'reason': 'local_asr_failed'}


async def extract_content(detail: dict, context, output_dir: Path, options: dict) -> dict:
    """Return bounded, URL-free results. Media/ASR/OCR are opt-in independently.

    Original subtitle URLs are inspected by default. APIRequestContext pre-buffers
    responses, so the byte cap bounds stored output, not a hostile server's traffic.
    OCR has no vetted local backend yet; arbitrary command options are ignored.
    """
    output_dir = Path(output_dir)
    options = options or {}
    result = {key: {'status': 'not_requested'} for key in ('media', 'asr', 'ocr')}
    result['subtitles'] = {'status': 'missing'}
    video = detail.get('video') or {}
    subtitle_url, subtitle_source = _subtitle_source(detail, video)
    timeout = 45_000
    if subtitle_source:
        state, body = await _fetch(context, subtitle_url, MAX_SUBTITLE_BYTES, timeout)
        result['subtitles'] = state
        if body is not None:
            path = _write_artifact(output_dir, 'subtitle.txt', body)
            try:
                segments = _segments(body)
                state.update(status='available' if segments else 'observed_empty', segments=segments,
                             source_path=subtitle_source,
                             artifact_path=path.name)
            except (ValueError, TypeError, AttributeError, UnicodeError):
                state.update(status='error', reason='unsupported_subtitle_format', artifact_path=path.name)
    wants_media = options.get('media') is True
    if wants_media:
        control = detail.get('video_control') or {}
        info = control.get('download_info') or {}
        if control.get('allow_download') is not True or info.get('fail_info') or info.get('level', 0) != 0:
            result['media'] = {'status': 'blocked', 'reason': 'download_policy'}
        else:
            address = video.get('download_addr') or {}
            urls = address.get('url_list') or []
            try:
                declared_size = int(address.get('data_size') or 0)
            except (ValueError, TypeError):
                declared_size = -1
            if not urls:
                result['media'] = {'status': 'missing', 'reason': 'media_url_missing'}
            elif declared_size < 0:
                result['media'] = {'status': 'blocked', 'reason': 'invalid_size'}
            elif declared_size > MAX_MEDIA_BYTES:
                result['media'] = {'status': 'blocked', 'reason': 'size_limit'}
            else:
                state, body = await _fetch(context, urls[0], MAX_MEDIA_BYTES, timeout, media=True)
                state['source_path'] = 'video.download_addr.url_list[0]'
                result['media'] = state
                if body is not None:
                    path = _write_artifact(output_dir, 'media.mp4', body)
                    metadata = await asyncio.to_thread(_probe, path)
                    state.update(artifact_path=path.name, **metadata)
                    if options.get('asr') is True:
                        result['asr'] = await asyncio.to_thread(_local_asr, path, output_dir, metadata)
    if options.get('asr') is True and result['asr']['status'] == 'not_requested':
        result['asr'] = {'status': 'unavailable', 'reason': 'media_required'}
    if options.get('ocr') is True:
        result['ocr'] = {'status': 'unavailable', 'reason': 'no_vetted_local_ocr_backend'}
    return result
