"""Transcribe an existing media file locally; never fetch platform data."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def timestamp(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{ms:03}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('media', type=Path)
    parser.add_argument('--model', default='small')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--model-cache-root', type=Path,
                        help='Shared model cache directory (default: output-dir/asr-models)')
    parser.add_argument('--output-prefix', default='transcript')
    parser.add_argument('--no-vad', action='store_true')
    args = parser.parse_args()
    media = args.media.resolve()
    out = (args.output_dir or media.parent).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(media)
    ], encoding='utf-8'))
    (out / 'asr-ffprobe.json').write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding='utf-8')
    if not any(s['codec_type'] == 'audio' for s in probe['streams']):
        raise RuntimeError('Media has no audio track; transcription not attempted')
    wav = out / 'audio.wav'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(media),
                    '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)], check=True)
    from faster_whisper import WhisperModel
    load_t0 = time.perf_counter()
    print(f'Loading {args.model} on CPU/int8', flush=True)
    model = WhisperModel(args.model, device='cpu', compute_type='int8', cpu_threads=4,
                         download_root=str((args.model_cache_root or out / 'asr-models').resolve()))
    model_load_seconds = time.perf_counter() - load_t0
    inference_t0 = time.perf_counter()
    # ffmpeg already decoded/resampled audio; avoid a second decoder dependency.
    import numpy as np
    with wave.open(str(wav), 'rb') as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != 16000:
            raise RuntimeError('Expected 16kHz mono signed 16-bit PCM')
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(np.float32) / 32768.0
    iterator, info = model.transcribe(audio, language='zh', beam_size=5, vad_filter=not args.no_vad,
                                      word_timestamps=True, condition_on_previous_text=False)
    segments = []
    for segment in iterator:
        item = asdict(segment)
        segments.append(item)
        print(f'{segment.start:.2f}-{segment.end:.2f}: {segment.text}', flush=True)
    result = {
        'label': '机器转写，未经人工校对；可能包含识别错误，未用 AI 补写',
        'source_media': str(media), 'media_sha256': sha256(media),
        'audio_sha256': sha256(wav), 'media_duration_seconds': float(probe['format']['duration']),
        'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
        'engine': 'faster-whisper', 'engine_version': importlib.metadata.version('faster-whisper'),
        'model': args.model, 'model_repository': f'Systran/faster-whisper-{args.model}',
        'device': 'cpu', 'compute_type': 'int8', 'language': info.language,
        'vad_filter': not args.no_vad,
        'language_probability': info.language_probability,
        'model_load_seconds': model_load_seconds,
        'inference_seconds': time.perf_counter() - inference_t0,
        'total_seconds': time.perf_counter() - t0,
        'vad_duration_seconds': info.duration_after_vad,
        'text': ''.join(s['text'] for s in segments).strip(), 'segments': segments,
    }
    (out / f'{args.output_prefix}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / f'{args.output_prefix}.txt').write_text(result['label'] + '\n\n' + result['text'] + '\n', encoding='utf-8')
    srt = '\n\n'.join(f"{i}\n{timestamp(s['start'])} --> {timestamp(s['end'])}\n{s['text'].strip()}"
                        for i, s in enumerate(segments, 1))
    (out / f'{args.output_prefix}.srt').write_text(srt + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('segments', 'text')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
