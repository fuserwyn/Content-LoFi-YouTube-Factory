from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .fetch_assets import ClipAsset


@dataclass
class RenderResult:
    output_path: Path
    concat_source_path: Path


def render_video_with_ffmpeg(
    clips: list[ClipAsset],
    track_path: Path,
    output_dir: Path,
    target_duration_seconds: int,
    width: int,
    height: int,
    fps: int,
) -> RenderResult:
    if not clips:
        raise RuntimeError("No clips available for rendering.")

    output_dir.mkdir(parents=True, exist_ok=True)
    concat_list_path = output_dir / "concat_list.txt"
    stitched_video_path = output_dir / "stitched.mp4"
    output_path = output_dir / "final.mp4"

    with concat_list_path.open("w", encoding="utf-8") as file:
        for clip in clips:
            file.write(f"file '{clip.local_path.as_posix()}'\n")

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            "-r",
            str(fps),
            "-an",
            str(stitched_video_path),
        ]
    )

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(stitched_video_path),
            "-i",
            str(track_path),
            "-t",
            str(target_duration_seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ]
    )

    return RenderResult(output_path=output_path, concat_source_path=concat_list_path)


def _run_ffmpeg(command: list[str]) -> None:
    proc = subprocess.run(command, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg command failed: {' '.join(command)}\n{proc.stderr}")
