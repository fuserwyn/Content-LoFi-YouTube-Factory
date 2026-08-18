"""Проход целиком: длинное видео юзера на входе — готовые шортсы на выходе.

Связывает три модуля, каждый из которых сам по себе ничего не решает:
транскрибацию, отбор хайлайтов и нарезку с прожигом субтитров.

Порядок неслучаен. Хайлайты отбираются по транскрипту, а субтитры режутся по
тем же пословным таймкодам, что и окна клипов, — поэтому транскрибация идёт
первой и её результат переиспользуется дважды. Транскрибировать повторно на
каждый клип означало бы платить за одно и то же по несколько раз.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .highlights import Highlight, find_highlights
from .shorts_cut import ShortClip, cut_short
from .subtitles import build_ass, window_words
from .transcribe import (
    DEFAULT_MODEL_SIZE as DEFAULT_WHISPER_MODEL,
    TranscriptSegment,
    Word,
    has_speech,
    probe_duration_seconds,
    transcribe,
)

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
DEFAULT_PRESET = "veryfast"
DEFAULT_CRF = 23


@dataclass
class PipelineResult:
    clips: list[ShortClip] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)
    segments: list[TranscriptSegment] = field(default_factory=list)
    source_duration_ms: int = 0
    # Ложь означает, что в исходнике нет речи: отбирать хайлайты не по чему
    # и субтитры писать не из чего. Причину важно вернуть наверх, чтобы бот
    # объяснил юзеру, а не молчал с пустым списком.
    had_speech: bool = False


def _all_words(segments: list[TranscriptSegment]) -> list[Word]:
    words: list[Word] = []
    for segment in segments:
        words.extend(segment.words)
    return words


def build_shorts(
    source_path: Path,
    output_dir: Path,
    *,
    anthropic_api_key: str = "",
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    whisper_download_root: str = "",
    language: str = "",
    max_count: int = 10,
    min_seconds: int = 20,
    max_seconds: int = 60,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    encode_preset: str = DEFAULT_PRESET,
    crf: int = DEFAULT_CRF,
    burn_subtitles: bool = True,
    render: bool = True,
    on_clip_ready: Callable[[ShortClip, Highlight], None] | None = None,
) -> PipelineResult:
    """Транскрибирует исходник, отбирает хайлайты и режет их в вертикальные клипы.

    ``on_clip_ready`` вызывается после каждого готового клипа — чтобы бот отдавал
    юзеру первый шортс, не дожидаясь, пока досчитаются остальные. Вместе с
    клипом передаётся хайлайт: в нём границы, заголовок и обоснование, без
    которых юзеру непонятно, откуда взялся фрагмент.
    """
    duration_ms = int(probe_duration_seconds(source_path) * 1000)
    result = PipelineResult(source_duration_ms=duration_ms)

    result.segments = transcribe(
        source_path,
        model_size=whisper_model,
        language=language,
        download_root=whisper_download_root,
    )
    result.had_speech = has_speech(result.segments)
    if not result.had_speech:
        return result

    result.highlights = find_highlights(
        result.segments,
        duration_ms,
        anthropic_api_key,
        max_count=max_count,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
    )

    # Разбор без нарезки: юзер сначала смотрит список фрагментов и
    # заказывает нужные. Рендер — самая тяжёлая часть прохода, и тратить
    # его на невостребованные ролики незачем.
    if not render:
        return result

    words = _all_words(result.segments)
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, highlight in enumerate(result.highlights, start=1):
        ass_text = ""
        if burn_subtitles:
            clip_words = window_words(words, highlight.start_ms, highlight.end_ms)
            if clip_words:
                ass_text = build_ass(clip_words, width, height)

        clip = cut_short(
            source_path=source_path,
            output_path=output_dir / f"{source_path.stem}_short_{index:02d}.mp4",
            start_ms=highlight.start_ms,
            end_ms=highlight.end_ms,
            width=width,
            height=height,
            fps=fps,
            encode_preset=encode_preset,
            crf=crf,
            ass_text=ass_text,
        )
        result.clips.append(clip)
        if on_clip_ready is not None:
            on_clip_ready(clip, highlight)

    return result
