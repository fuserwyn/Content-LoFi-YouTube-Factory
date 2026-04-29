from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import random
import subprocess
from typing import Callable

from .select_track import SUPPORTED_EXTENSIONS


@dataclass
class TikTokClipResult:
    output_path: Path
    track_path: Path
    start_second: int
    duration_second: int


def create_tiktok_cuts(
    source_video_path: Path,
    tracks_dir: Path,
    output_dir: Path,
    clips_count: int,
    clip_seconds: int,
    width: int,
    height: int,
    fps: int,
    encode_preset: str,
    crf: int,
    clip_min_seconds: int | None = None,
    clip_max_seconds: int | None = None,
    on_clip_ready: Callable[[TikTokClipResult], None] | None = None,
) -> list[TikTokClipResult]:
    if not source_video_path.exists():
        raise RuntimeError(f"TikTok source video not found: {source_video_path}")

    tracks = _list_tracks(tracks_dir)
    if not tracks:
        raise RuntimeError(f"No tracks available for TikTok cuts in: {tracks_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_duration = _probe_media_duration_seconds(source_video_path)
    if source_duration is None:
        raise RuntimeError(f"Unable to probe source duration for TikTok cuts: {source_video_path}")

    timeline = _build_timeline(
        duration_seconds=source_duration,
        clips_count=clips_count,
        clip_seconds=clip_seconds,
        clip_min_seconds=clip_min_seconds,
        clip_max_seconds=clip_max_seconds,
    )
    shuffled_tracks = tracks[:]
    random.shuffle(shuffled_tracks)

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: list[TikTokClipResult] = []
    for index, (start_second, duration_second) in enumerate(timeline):
        track_path = shuffled_tracks[index % len(shuffled_tracks)]
        output_path = output_dir / f"tiktok_{run_stamp}_{index + 1:02d}.mp4"
        _render_one_clip(
            source_video_path=source_video_path,
            track_path=track_path,
            output_path=output_path,
            start_second=start_second,
            duration_second=duration_second,
            width=width,
            height=height,
            fps=fps,
            encode_preset=encode_preset,
            crf=crf,
        )
        results.append(
            TikTokClipResult(
                output_path=output_path,
                track_path=track_path,
                start_second=start_second,
                duration_second=duration_second,
            )
        )
        if on_clip_ready is not None:
            on_clip_ready(results[-1])
    return results


def _list_tracks(tracks_dir: Path) -> list[Path]:
    return [
        path
        for path in tracks_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def _probe_media_duration_seconds(path: Path) -> int | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return None


def _build_timeline(
    duration_seconds: int,
    clips_count: int,
    clip_seconds: int,
    clip_min_seconds: int | None,
    clip_max_seconds: int | None,
) -> list[tuple[int, int]]:
    if clips_count <= 0:
        # Auto mode: split sequentially until source is exhausted.
        segments: list[tuple[int, int]] = []
        elapsed = 0
        min_sec = max(5, clip_min_seconds or clip_seconds)
        max_sec = max(min_sec, clip_max_seconds or clip_seconds)
        while elapsed < duration_seconds:
            remaining = duration_seconds - elapsed
            duration = remaining if remaining <= min_sec else min(remaining, random.randint(min_sec, max_sec))
            segments.append((elapsed, max(1, duration)))
            elapsed += duration
        return segments

    max_start = max(0, duration_seconds - clip_seconds)
    if clips_count <= 1:
        start = 0 if max_start == 0 else random.randint(0, max_start)
        return [(start, min(clip_seconds, max(1, duration_seconds - start)))]

    if max_start == 0:
        return [(0, max(1, duration_seconds)) for _ in range(clips_count)]

    starts: list[tuple[int, int]] = []
    step = max_start / clips_count
    for i in range(clips_count):
        bucket_start = int(i * step)
        bucket_end = int((i + 1) * step) if i < clips_count - 1 else max_start
        if bucket_end <= bucket_start:
            start = bucket_start
            starts.append((start, min(clip_seconds, max(1, duration_seconds - start))))
            continue
        start = random.randint(bucket_start, bucket_end)
        starts.append((start, min(clip_seconds, max(1, duration_seconds - start))))
    return starts


def _render_one_clip(
    source_video_path: Path,
    track_path: Path,
    output_path: Path,
    start_second: int,
    duration_second: int,
    width: int,
    height: int,
    fps: int,
    encode_preset: str,
    crf: int,
) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_second),
        "-t",
        str(duration_second),
        "-i",
        str(source_video_path),
        "-stream_loop",
        "-1",
        "-i",
        str(track_path),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
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
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg TikTok render failed: {' '.join(cmd)}\n{proc.stderr}")
