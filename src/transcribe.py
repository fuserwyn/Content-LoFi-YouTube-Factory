"""Транскрибация исходника локальным Whisper, с пословными таймкодами.

Пословные тайминги нужны дважды: сопоставить отобранный хайлайт с местом в
видео и синхронизировать субтитры с речью. Поэтому LLM с аудио на входе здесь
не годится — текст она выдаст, а миллисекунды выдумает.

Считаем на CPU через faster-whisper (CTranslate2): ключей и счетов не нужно,
платим только временем. Времени уходит много — замер на 116 секундах русской
речи, int8, Apple Silicon:

    tiny    x1.6 реального времени  ->  2 часа звука за ~73 минуты
    small   x0.3 реального времени  ->  2 часа звука за ~6 часов

На процессоре Railway — медленнее. Практический вывод: локальный бэкенд годится
для отладки и коротких исходников, но длинный подкаст на нём обрабатывать
нельзя, юзер столько не ждёт. Под лонги нужен API (Cloudflare Workers AI —
$0.00051 за минуту, то есть шесть центов за двухчасовое видео).

Качество тоже разное: на том же файле ``small`` распознал 232 слова против 186
у ``tiny``. Транскрипт — вход для отбора хайлайтов, так что его пробелы прямо
портят главную функцию продукта.

Веса модели скачиваются при первом запуске. На Railway их стоит держать на
волюме (``download_root``), иначе каждый передеплой качает заново.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import tempfile
import threading

from .ffmpeg_utils import finalize_ffmpeg_command

DEFAULT_MODEL_SIZE = "small"
# int8 примерно вчетверо быстрее float32 на CPU при незначительной потере
# качества — для CPU-инференса это единственный практичный режим.
DEFAULT_COMPUTE_TYPE = "int8"

# 16 кГц моно — то, что Whisper ждёт на входе; больше ему не нужно.
AUDIO_SAMPLE_RATE = "16000"

# Загрузка весов занимает секунды и память, а модель между вызовами не меняется.
_MODEL_CACHE: dict[tuple, object] = {}
_MODEL_LOCK = threading.Lock()


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
    """Вынимает дорожку в 16 кГц моно WAV — формат, который Whisper ждёт.

    Декодировать видеопоток на каждом проходе распознавания незачем, поэтому
    звук вынимается один раз заранее.
    """
    if not source_path.exists():
        raise TranscriptionError(f"Source not found: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-vn",
        "-ac", "1",
        "-ar", AUDIO_SAMPLE_RATE,
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    proc = subprocess.run(finalize_ffmpeg_command(cmd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscriptionError(f"Audio extraction failed: {proc.stderr.strip()[:500]}")
    return output_path


def load_model(
    model_size: str = DEFAULT_MODEL_SIZE,
    *,
    device: str = "cpu",
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    download_root: str = "",
):
    """Возвращает модель из кеша, загружая её при первом обращении."""
    key = (model_size, device, compute_type, download_root)
    with _MODEL_LOCK:
        if key not in _MODEL_CACHE:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover
                raise TranscriptionError(
                    "faster-whisper is required for local transcription"
                ) from exc
            _MODEL_CACHE[key] = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=download_root or None,
            )
        return _MODEL_CACHE[key]


def _to_segments(raw_segments) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for raw in raw_segments:
        text = (raw.text or "").strip()
        if not text:
            continue
        words = [
            Word(
                start_ms=int(w.start * 1000),
                end_ms=int(w.end * 1000),
                text=(w.word or "").strip(),
            )
            for w in (raw.words or [])
            if (w.word or "").strip()
        ]
        segments.append(
            TranscriptSegment(
                start_ms=int(raw.start * 1000),
                end_ms=int(raw.end * 1000),
                text=text,
                words=words,
            )
        )
    return segments


def transcribe(
    source_path: Path,
    *,
    model_size: str = DEFAULT_MODEL_SIZE,
    language: str = "",
    device: str = "cpu",
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    download_root: str = "",
) -> list[TranscriptSegment]:
    """Транскрибирует видео или аудио. Возвращает сегменты в абсолютных мс от начала."""
    model = load_model(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        audio_path = extract_audio(source_path, Path(tmp) / "audio.wav")
        try:
            raw_segments, _info = model.transcribe(
                str(audio_path),
                language=language.strip() or None,
                word_timestamps=True,
            )
            # faster-whisper отдаёт генератор и считает лениво — материализуем
            # до выхода из TemporaryDirectory, иначе файл исчезнет из-под него.
            segments = _to_segments(raw_segments)
        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001 — бэкенд бросает свои типы
            raise TranscriptionError(f"Whisper failed: {exc}") from exc

    segments.sort(key=lambda s: s.start_ms)
    return segments


def has_speech(segments: list[TranscriptSegment], min_words: int = 5) -> bool:
    """Есть ли в исходнике речь. Молчаливое видео субтитрами не портим."""
    return sum(len(s.words) or len(s.text.split()) for s in segments) >= min_words
