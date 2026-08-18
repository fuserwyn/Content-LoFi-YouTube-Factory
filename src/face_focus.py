"""Где в кадре люди — чтобы вертикальная обрезка не срезала им головы.

Обрезка по центру исходит из того, что главное в середине кадра. В разговорном
видео это неверно: собеседники сидят по краям, и центральная рамка ловит стену
между ними. Поэтому ищем лица и двигаем рамку к ним.

Детектор намеренно простой (Haar-каскад OpenCV): он работает на CPU за
миллисекунды и отвечает на единственный нужный вопрос — где по горизонтали
находятся люди. Точные контуры и распознавание личностей здесь не нужны.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from statistics import median

from .ffmpeg_utils import finalize_ffmpeg_command

LOGGER = logging.getLogger("content_factory")

# Больше кадров — устойчивее медиана, но дольше. Пяти хватает, чтобы пережить
# один кадр с отвернувшимся человеком или сменой плана.
SAMPLE_FRAMES = 5

# Лица мельче этой доли ширины кадра — статисты на заднем плане, вести за ними
# рамку не нужно.
MIN_FACE_RATIO = 0.04


def _grab_frames(source: Path, start_ms: int, end_ms: int, out_dir: Path) -> list[Path]:
    """Равномерно вынимает кадры из окна клипа."""
    duration = max(1, (end_ms - start_ms) // 1000)
    step = max(1, duration // SAMPLE_FRAMES)
    frames: list[Path] = []
    for index in range(SAMPLE_FRAMES):
        at = start_ms / 1000 + index * step
        if at * 1000 >= end_ms:
            break
        path = out_dir / f"frame_{index:02d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{at:.3f}", "-i", str(source),
            "-frames:v", "1", "-q:v", "5", str(path),
        ]
        proc = subprocess.run(finalize_ffmpeg_command(cmd), check=False, capture_output=True)
        if proc.returncode == 0 and path.exists():
            frames.append(path)
    return frames


def _faces_in(path: Path) -> list[tuple[int, int]]:
    """(центр поx, ширина) найденных лиц в пикселях."""
    import cv2

    image = cv2.imread(str(path))
    if image is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    frame_width = image.shape[1]
    return [
        (int(x + w / 2), int(w))
        for x, _y, w, _h in found
        if w >= frame_width * MIN_FACE_RATIO
    ]


def focus_fraction(source: Path, start_ms: int, end_ms: int) -> float | None:
    """Горизонтальное положение лиц как доля ширины кадра, 0..1.

    None означает «лиц не нашли» — тогда вызывающий код обрезает по центру,
    как и раньше. Пустой результат это нормальный исход, а не ошибка: в кадре
    может не быть людей вовсе.
    """
    try:
        import cv2  # noqa: F401
    except ImportError:
        LOGGER.info("FOCUS: opencv недоступен, обрезаю по центру")
        return None

    with tempfile.TemporaryDirectory(prefix="focus_") as tmp:
        tmp_dir = Path(tmp)
        frames = _grab_frames(source, start_ms, end_ms, tmp_dir)
        if not frames:
            return None

        centers: list[float] = []
        for frame in frames:
            try:
                import cv2

                image = cv2.imread(str(frame))
                if image is None:
                    continue
                width = image.shape[1]
                for center_x, _ in _faces_in(frame):
                    centers.append(center_x / width)
            except Exception:  # noqa: BLE001 — детектор не должен ронять рендер
                LOGGER.exception("FOCUS: детектор упал на кадре")
                return None

    if not centers:
        return None
    # Медиана, а не среднее: один ложный сработ на краю кадра не должен
    # утащить рамку за собой.
    return float(median(centers))


def crop_offset(scaled_width: int, out_width: int, fraction: float | None) -> int:
    """Смещение рамки обрезки в пикселях так, чтобы лица оказались в центре.

    Без лиц (``fraction is None``) возвращает центр — прежнее поведение.
    """
    room = max(0, scaled_width - out_width)
    if fraction is None:
        return room // 2
    wanted = fraction * scaled_width - out_width / 2
    return int(min(max(wanted, 0), room))
