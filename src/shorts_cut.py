"""Нарезка вертикальных шортсов из лонга юзера с сохранением оригинального звука.

Отдельный модуль, а не режим ``tiktok_cuts``: там звук намеренно подменяется
музыкальным треком (``-map 1:a:0``), потому что лофи-видео речи не содержит.
Здесь всё наоборот — речь и есть содержание, поэтому дорожка берётся из
исходника (``-map 0:a:0``), а поверх прожигаются субтитры.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .ffmpeg_utils import finalize_ffmpeg_command


@dataclass
class ShortClip:
    path: Path
    start_ms: int
    end_ms: int
    has_subtitles: bool

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class ShortsCutError(RuntimeError):
    pass


def _build_filter(width: int, height: int, fps: int, ass_name: str) -> str:
    """Кадрируем в 9:16 обрезкой по центру, затем поверх кладём субтитры.

    Порядок важен: ``ass`` после ``crop``, иначе подпись отрендерится в
    исходном разрешении и уедет вместе с обрезкой.
    """
    chain = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        # Соотношение сторон пикселя наследуется от исходника. Если оно не
        # единичное, кадр 1080x1920 отображается не как 9:16, и плеер тянет
        # картинку — размер верный, а видео выглядит невертикальным.
        "setsar=1",
        f"fps={fps}",
    ]
    if ass_name:
        chain.append(f"ass={ass_name}")
    return ",".join(chain)


def cut_short(
    source_path: Path,
    output_path: Path,
    start_ms: int,
    end_ms: int,
    width: int,
    height: int,
    fps: int,
    encode_preset: str,
    crf: int,
    ass_text: str = "",
) -> ShortClip:
    """Режет окно ``[start_ms, end_ms)`` в вертикальный клип.

    ``ass_text`` — готовый ASS-документ с таймкодами, сдвинутыми к началу клипа
    (см. ``subtitles.window_words`` + ``subtitles.build_ass``). Пустой — без
    субтитров, так обрабатывается видео без речи.
    """
    if not source_path.exists():
        raise ShortsCutError(f"Source video not found: {source_path}")
    if end_ms <= start_ms:
        raise ShortsCutError(f"Empty window: start={start_ms} end={end_ms}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ASS кладём рядом с результатом и передаём ffmpeg голое имя файла, запуская
    # его с cwd в этой папке. Это надёжнее, чем экранировать путь: в синтаксисе
    # фильтров спецсимволами являются и ':', и ',', и '\', и кавычки.
    ass_name = ""
    ass_path: Path | None = None
    if ass_text.strip():
        ass_path = output_path.parent / f"{output_path.stem}.ass"
        ass_path.write_text(ass_text, encoding="utf-8")
        ass_name = ass_path.name

    duration_s = (end_ms - start_ms) / 1000

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_ms / 1000:.3f}",
        "-t", f"{duration_s:.3f}",
        "-i", str(source_path.resolve()),
        "-vf", _build_filter(width, height, fps, ass_name),
        "-map", "0:v:0",
        # '?' делает дорожку необязательной: немое видео не должно ронять рендер.
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", encode_preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path.resolve()),
    ]

    proc = subprocess.run(
        finalize_ffmpeg_command(cmd),
        cwd=str(output_path.parent),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ShortsCutError(f"FFmpeg shorts render failed: {proc.stderr.strip()[:500]}")

    if ass_path is not None and ass_path.exists():
        ass_path.unlink()

    return ShortClip(
        path=output_path,
        start_ms=start_ms,
        end_ms=end_ms,
        has_subtitles=bool(ass_name),
    )
