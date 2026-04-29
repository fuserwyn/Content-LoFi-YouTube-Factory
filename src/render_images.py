from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .generate_images import GeneratedImage


@dataclass
class ImageRenderResult:
    output_path: Path
    concat_source_path: Path
    image_count: int
    target_duration_seconds: int


def render_video_from_images(
    images: list[GeneratedImage],
    track_path: Path,
    output_dir: Path,
    width: int,
    height: int,
    fps: int,
    target_duration_seconds: int,
    scene_seconds: int,
    encode_preset: str,
    crf: int,
) -> ImageRenderResult:
    if not images:
        raise RuntimeError("No generated images available for image render.")

    output_dir.mkdir(parents=True, exist_ok=True)
    concat_path = output_dir / "images_concat.txt"
    output_path = output_dir / "final.mp4"

    with concat_path.open("w", encoding="utf-8") as file:
        for image in images:
            file.write(f"file '{image.local_path.as_posix()}'\n")
            file.write(f"duration {scene_seconds}\n")
        file.write(f"file '{images[-1].local_path.as_posix()}'\n")

    # Slow zoom for still images + mild frame interpolation feel with higher fps.
    vf = (
        f"zoompan=z='min(zoom+0.0005,1.08)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={max(1, scene_seconds * fps)}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-i",
        str(track_path),
        "-vf",
        vf,
        "-t",
        str(target_duration_seconds),
        "-c:v",
        "libx264",
        "-preset",
        encode_preset,
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_path),
    ]
    _run_ffmpeg(cmd)

    return ImageRenderResult(
        output_path=output_path,
        concat_source_path=concat_path,
        image_count=len(images),
        target_duration_seconds=target_duration_seconds,
    )


def _run_ffmpeg(command: list[str]) -> None:
    proc = subprocess.run(command, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg command failed: {' '.join(command)}\n{proc.stderr}")
