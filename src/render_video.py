from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import random
import re
import subprocess

from .fetch_assets import ClipAsset

LOGGER = logging.getLogger("content_factory")
FFMPEG_TIME_RE = re.compile(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)")


@dataclass
class RenderResult:
    output_path: Path
    concat_source_path: Path
    planned_seconds: int
    final_target_seconds: int
    looped_stitched_video: bool


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
    no_repeat_clips_in_single_video: bool = False,
    allow_shorter_unique_video: bool = True,
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
        avoid_clip_reuse=no_repeat_clips_in_single_video,
        allow_shorter_output=allow_shorter_unique_video,
    )
    planned_seconds = sum(item.duration_second for item in motion_plan)
    if planned_seconds <= 0:
        raise RuntimeError("Unable to build a valid render plan.")
    if no_repeat_clips_in_single_video and not allow_shorter_unique_video and planned_seconds < target_duration_seconds:
        raise RuntimeError(
            f"Not enough unique clips for strict no-repeat mode: planned={planned_seconds}s target={target_duration_seconds}s"
        )

    normalized_files: list[Path] = []
    LOGGER.info("RENDER: preparing %d dynamic segments", len(motion_plan))
    for index, segment in enumerate(motion_plan):
        normalized_file = normalized_dir / f"segment_{index:03d}.mp4"
        normalized_files.append(normalized_file)
        LOGGER.info(
            "RENDER: segment %d/%d | clip_id=%s | start=%ss | duration=%ss",
            index + 1,
            len(motion_plan),
            segment.clip.source_video_id,
            segment.start_second,
            segment.duration_second,
        )
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
            ],
            progress_label=f"segment {index + 1}/{len(motion_plan)}",
            expected_duration_seconds=segment.duration_second,
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

    final_target_seconds = target_duration_seconds
    final_cmd = ["ffmpeg", "-y"]
    should_loop_stitched_video = not no_repeat_clips_in_single_video
    if no_repeat_clips_in_single_video:
        # No-repeat mode never loops stitched video; resulting duration can be shorter
        # than the track when unique source material is insufficient.
        final_target_seconds = min(target_duration_seconds, planned_seconds)
        LOGGER.info("RENDER: strict no-repeat mode, final_target_seconds=%ss", final_target_seconds)

    if should_loop_stitched_video:
        final_cmd.extend(["-stream_loop", "-1"])

    final_cmd.extend(
        [
            "-i",
            str(stitched_video_path),
            "-i",
            str(track_path),
            "-t",
            str(final_target_seconds),
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
    _run_ffmpeg(
        final_cmd,
        progress_label="final render",
        expected_duration_seconds=final_target_seconds,
    )

    return RenderResult(
        output_path=output_path,
        concat_source_path=concat_list_path,
        planned_seconds=planned_seconds,
        final_target_seconds=final_target_seconds,
        looped_stitched_video=should_loop_stitched_video,
    )


def _run_ffmpeg(
    command: list[str],
    progress_label: str = "",
    expected_duration_seconds: int = 0,
) -> None:
    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    last_percent_bucket = -1
    stderr_lines: list[str] = []
    assert proc.stderr is not None
    for line in proc.stderr:
        stderr_lines.append(line)
        if expected_duration_seconds <= 0:
            continue
        parsed_seconds = _extract_ffmpeg_time_seconds(line)
        if parsed_seconds is None:
            continue
        percent = min(100, int((parsed_seconds / expected_duration_seconds) * 100))
        bucket = percent // 10
        if bucket > last_percent_bucket:
            last_percent_bucket = bucket
            LOGGER.info("RENDER: %s progress %d%%", progress_label or "ffmpeg", bucket * 10)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg command failed: {' '.join(command)}\n{''.join(stderr_lines)}")


def _extract_ffmpeg_time_seconds(line: str) -> float | None:
    match = FFMPEG_TIME_RE.search(line)
    if not match:
        return None
    return _hhmmss_to_seconds(match.group(1))


def _hhmmss_to_seconds(value: str) -> float:
    hh, mm, ss = value.split(":")
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def _build_motion_plan(
    clips: list[ClipAsset],
    target_duration_seconds: int,
    min_segment_seconds: int,
    max_segment_seconds: int,
    avoid_clip_reuse: bool = False,
    allow_shorter_output: bool = True,
) -> list[MotionSegment]:
    if avoid_clip_reuse:
        return _build_unique_motion_plan(
            clips=clips,
            target_duration_seconds=target_duration_seconds,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
            allow_shorter_output=allow_shorter_output,
        )

    plan: list[MotionSegment] = []
    elapsed = 0
    if not clips:
        return plan

    available = clips[:]
    random.shuffle(available)
    prev_clip_id: int | None = None

    while elapsed < target_duration_seconds:
        if not available:
            if avoid_clip_reuse:
                break
            available = clips[:]
            random.shuffle(available)
            # Avoid immediate repetition when more than one clip exists.
            if len(available) > 1 and prev_clip_id is not None and available[0].source_video_id == prev_clip_id:
                available.append(available.pop(0))

        clip = available.pop(0)

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
        prev_clip_id = clip.source_video_id

    return plan


def _build_unique_motion_plan(
    clips: list[ClipAsset],
    target_duration_seconds: int,
    min_segment_seconds: int,
    max_segment_seconds: int,
    allow_shorter_output: bool,
) -> list[MotionSegment]:
    # Build non-overlapping segments per clip, then shuffle to avoid visible sequencing.
    unique_pool: list[MotionSegment] = []
    for clip in clips:
        usable_seconds = max(1, clip.duration - 1)
        start_second = 0
        while start_second < usable_seconds:
            remaining_in_clip = usable_seconds - start_second
            if remaining_in_clip < min_segment_seconds and start_second > 0:
                break
            segment_duration = min(max_segment_seconds, remaining_in_clip)
            unique_pool.append(
                MotionSegment(
                    clip=clip,
                    start_second=start_second,
                    duration_second=segment_duration,
                )
            )
            start_second += segment_duration

    if not unique_pool:
        return []

    random.shuffle(unique_pool)

    plan: list[MotionSegment] = []
    elapsed = 0
    prev_clip_id: int | None = None
    pool = unique_pool[:]

    while elapsed < target_duration_seconds and pool:
        picked_index = 0
        if prev_clip_id is not None:
            for i, candidate in enumerate(pool):
                if candidate.clip.source_video_id != prev_clip_id:
                    picked_index = i
                    break

        segment = pool.pop(picked_index)
        remaining_target = target_duration_seconds - elapsed
        segment_duration = min(segment.duration_second, remaining_target)
        if segment_duration <= 0:
            break

        plan.append(
            MotionSegment(
                clip=segment.clip,
                start_second=segment.start_second,
                duration_second=segment_duration,
            )
        )
        elapsed += segment_duration
        prev_clip_id = segment.clip.source_video_id

    if not allow_shorter_output and elapsed < target_duration_seconds:
        return []

    return plan
