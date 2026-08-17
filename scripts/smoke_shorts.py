"""Смоук-тест конвейера нарезки прямо в развёрнутом окружении.

Юнит-тесты мокают ffmpeg, поэтому не проверяют главного: что в конкретной
сборке ffmpeg есть libass, что шрифт с кириллицей находится и что субтитры
реально появляются в кадре. Здесь всё это прогоняется по-настоящему.

    python scripts/smoke_shorts.py

Выходит с ненулевым кодом, если что-то из этого не работает.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.shorts_cut import cut_short  # noqa: E402
from src.subtitles import build_ass  # noqa: E402
from src.transcribe import Word  # noqa: E402

WIDTH, HEIGHT, FPS = 1080, 1920, 30


def _make_source(path: Path, seconds: int = 8) -> Path:
    """Синтетический исходник: движущаяся картинка плюс тон 440 Гц."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={FPS}:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(path),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"не удалось собрать исходник: {proc.stderr[-400:]}")
    return path


def _probe(path: Path, entries: str) -> str:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries,
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=False, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _mean_volume(path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        check=False, capture_output=True, text=True,
    )
    for line in proc.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].strip().split()[0])
    return 0.0


def main() -> int:
    words = [
        Word(0, 800, "Проверка"),
        Word(900, 1700, "субтитров"),
        Word(2400, 3200, "кириллицей"),
    ]

    with tempfile.TemporaryDirectory(prefix="smoke_shorts_") as tmp:
        tmp_dir = Path(tmp)
        source = _make_source(tmp_dir / "source.mp4")

        plain = cut_short(
            source_path=source, output_path=tmp_dir / "plain.mp4",
            start_ms=1000, end_ms=5000,
            width=WIDTH, height=HEIGHT, fps=FPS,
            encode_preset="ultrafast", crf=30,
        )
        subbed = cut_short(
            source_path=source, output_path=tmp_dir / "subbed.mp4",
            start_ms=1000, end_ms=5000,
            width=WIDTH, height=HEIGHT, fps=FPS,
            encode_preset="ultrafast", crf=30,
            ass_text=build_ass(words, WIDTH, HEIGHT),
        )

        size = _probe(subbed.path, "stream=width,height").split("\n")
        codecs = _probe(subbed.path, "stream=codec_type").split("\n")
        volume = _mean_volume(subbed.path)
        plain_bytes = plain.path.stat().st_size
        subbed_bytes = subbed.path.stat().st_size

        checks = [
            ("кадр 1080x1920", size[:2] == [str(WIDTH), str(HEIGHT)]),
            ("дорожка звука на месте", "audio" in codecs),
            ("звук не тишина", volume > -60.0),
            ("субтитры попали в кадр", subbed_bytes > plain_bytes),
        ]

        print(f"без сабов: {plain_bytes:>9} байт")
        print(f"с сабами : {subbed_bytes:>9} байт  (+{subbed_bytes - plain_bytes})")
        print(f"громкость: {volume} dB")
        print()
        for label, ok in checks:
            print(f"  {'OK  ' if ok else 'ПРОВАЛ'} {label}")

        failed = [label for label, ok in checks if not ok]
        if failed:
            print(f"\nне прошло: {', '.join(failed)}")
            return 1

    print("\nвсё прошло")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
