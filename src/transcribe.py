"""Транскрибация исходника через Whisper API с пословными таймкодами.

Пословные тайминги нужны, чтобы субтитры в шортсе шли короткими строками в такт
речи, а не висели абзацем на весь клип.

У API жёсткий лимит 25 МБ на файл, поэтому дорожка сначала вынимается из видео и
жмётся в opus 16 кбит/с моно: два часа ≈ 14 МБ и влезают целиком. Если исходник
длиннее, файл режется на куски, а таймкоды сдвигаются обратно в абсолютные.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import math
import subprocess
import tempfile

import requests

from .ffmpeg_utils import finalize_ffmpeg_command

WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-1"

# Хард-лимит Whisper API. Держим запас — multipart добавляет накладные.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

# 16 кбит/с моно хватает для распознавания речи и даёт ~7 МБ на час.
AUDIO_BITRATE = "16k"
AUDIO_SAMPLE_RATE = "16000"


@dataclass
class Word:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)


class TranscriptionError(RuntimeError):
    pass


def probe_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscriptionError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise TranscriptionError(f"ffprobe returned no duration for {path}") from exc


def extract_audio(source_path: Path, output_path: Path) -> Path:
    """Вынимает дорожку в opus моно 16 кГц — минимальный размер без потери разборчивости."""
    if not source_path.exists():
        raise TranscriptionError(f"Source not found: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-vn",
        "-ac", "1",
        "-ar", AUDIO_SAMPLE_RATE,
        "-c:a", "libopus",
        "-b:a", AUDIO_BITRATE,
        str(output_path),
    ]
    proc = subprocess.run(finalize_ffmpeg_command(cmd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscriptionError(f"Audio extraction failed: {proc.stderr.strip()[:500]}")
    return output_path


def _slice_audio(source_path: Path, output_path: Path, start_s: float, duration_s: float) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-t", f"{duration_s:.3f}",
        "-i", str(source_path),
        "-c", "copy",
        str(output_path),
    ]
    proc = subprocess.run(finalize_ffmpeg_command(cmd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscriptionError(f"Audio slicing failed: {proc.stderr.strip()[:500]}")
    return output_path


def _chunk_plan(duration_s: float, size_bytes: int) -> list[tuple[float, float]]:
    """(start, duration) кусков так, чтобы каждый влезал в лимит API."""
    if size_bytes <= MAX_UPLOAD_BYTES:
        return [(0.0, duration_s)]
    parts = math.ceil(size_bytes / MAX_UPLOAD_BYTES)
    step = duration_s / parts
    return [(i * step, step) for i in range(parts)]


def _call_whisper(audio_path: Path, api_key: str, language: str = "") -> dict:
    data = [
        ("model", WHISPER_MODEL),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("timestamp_granularities[]", "segment"),
    ]
    if language.strip():
        data.append(("language", language.strip()))

    with audio_path.open("rb") as handle:
        response = requests.post(
            WHISPER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files={"file": (audio_path.name, handle, "audio/ogg")},
            timeout=600,
        )
    if response.status_code != 200:
        raise TranscriptionError(
            f"Whisper API {response.status_code}: {response.text[:300]}"
        )
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise TranscriptionError("Whisper API returned non-JSON response") from exc


def _parse_response(payload: dict, offset_ms: int) -> list[TranscriptSegment]:
    words = [
        Word(
            start_ms=int(float(w.get("start", 0)) * 1000) + offset_ms,
            end_ms=int(float(w.get("end", 0)) * 1000) + offset_ms,
            text=str(w.get("word", "")).strip(),
        )
        for w in payload.get("words") or []
        if str(w.get("word", "")).strip()
    ]

    segments: list[TranscriptSegment] = []
    for raw in payload.get("segments") or []:
        start_ms = int(float(raw.get("start", 0)) * 1000) + offset_ms
        end_ms = int(float(raw.get("end", 0)) * 1000) + offset_ms
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                words=[w for w in words if start_ms <= w.start_ms < end_ms],
            )
        )

    # Гранулярность segment иногда не приходит — тогда собираем из слов,
    # чтобы вызывающий код всегда получал непустой результат.
    if not segments and words:
        segments.append(
            TranscriptSegment(
                start_ms=words[0].start_ms,
                end_ms=words[-1].end_ms,
                text=" ".join(w.text for w in words),
                words=words,
            )
        )
    return segments


def transcribe(source_path: Path, api_key: str, language: str = "") -> list[TranscriptSegment]:
    """Транскрибирует видео или аудио. Возвращает сегменты в абсолютных мс от начала."""
    if not api_key.strip():
        raise TranscriptionError("Whisper API key is empty")

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        tmp_dir = Path(tmp)
        audio_path = extract_audio(source_path, tmp_dir / "audio.ogg")
        size_bytes = audio_path.stat().st_size
        duration_s = probe_duration_seconds(audio_path)

        segments: list[TranscriptSegment] = []
        for index, (start_s, chunk_s) in enumerate(_chunk_plan(duration_s, size_bytes)):
            if index == 0 and size_bytes <= MAX_UPLOAD_BYTES:
                chunk_path = audio_path
            else:
                chunk_path = _slice_audio(
                    audio_path, tmp_dir / f"chunk_{index}.ogg", start_s, chunk_s
                )
            payload = _call_whisper(chunk_path, api_key, language)
            segments.extend(_parse_response(payload, offset_ms=int(start_s * 1000)))

    segments.sort(key=lambda s: s.start_ms)
    return segments


def has_speech(segments: list[TranscriptSegment], min_words: int = 5) -> bool:
    """Есть ли в исходнике речь. Молчаливое видео субтитрами не портим."""
    return sum(len(s.words) or len(s.text.split()) for s in segments) >= min_words
