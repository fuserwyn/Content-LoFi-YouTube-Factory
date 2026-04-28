from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import subprocess

from .fetch_assets import ClipAsset


@dataclass
class RenderResult:
    output_path: Path
    concat_source_path: Path


@dataclass
class MotionSegment:
    clip: ClipAsset
    start_second: int
    duration_second: int


def render_video_with_ffmpeg(
    clips: list[ClipAsset],
    track_path: Path,
    output_dir: Path,
    target_duration_seconds: int,
    width: int,
    height: int,
    fps: int,
    encode_preset: str = "veryfast",
    crf: int = 23,
) -> RenderResult:
    if not clips:
        raise RuntimeError("No clips available for rendering.")

    output_dir.mkdir(parents=True, exist_ok=True)
    concat_list_path = output_dir / "concat_list.txt"
    stitched_video_path = output_dir / "stitched.mp4"
    output_path = output_dir / "final.mp4"
    normalized_dir = output_dir / "normalized_clips"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    # Create short motion segments from different parts of clips to avoid static-looking output.
    motion_plan = _build_motion_plan(
        clips=clips,
        target_duration_seconds=target_duration_seconds,
        min_segment_seconds=6,
        max_segment_seconds=12,
    )

    normalized_files: list[Path] = []
    for index, segment in enumerate(motion_plan):
        normalized_file = normalized_dir / f"segment_{index:03d}.mp4"
        normalized_files.append(normalized_file)
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(segment.start_second),
                "-t",
                str(segment.duration_second),
                "-i",
                str(segment.clip.local_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                encode_preset,
                "-pix_fmt",
                "yuv420p",
                str(normalized_file),
            ]
        )

    with concat_list_path.open("w", encoding="utf-8") as file:
        for segment_file in normalized_files:
            file.write(f"file '{segment_file.as_posix()}'\n")

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
            encode_preset,
            "-crf",
            str(crf),
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


def _build_motion_plan(
    clips: list[ClipAsset],
    target_duration_seconds: int,
    min_segment_seconds: int,
    max_segment_seconds: int,
) -> list[MotionSegment]:
    plan: list[MotionSegment] = []
    elapsed = 0
    clip_index = 0
    if not clips:
        return plan

    while elapsed < target_duration_seconds:
        clip = clips[clip_index % len(clips)]
        clip_index += 1

        max_available = max(1, clip.duration - 1)
        segment_duration = min(random.randint(min_segment_seconds, max_segment_seconds), max_available)
        segment_duration = min(segment_duration, target_duration_seconds - elapsed)
        if segment_duration <= 0:
            break

        latest_start = max(0, clip.duration - segment_duration - 1)
        start_second = random.randint(0, latest_start) if latest_start > 0 else 0

        plan.append(
            MotionSegment(
                clip=clip,
                start_second=start_second,
                duration_second=segment_duration,
            )
        )
        elapsed += segment_duration

    return plan
