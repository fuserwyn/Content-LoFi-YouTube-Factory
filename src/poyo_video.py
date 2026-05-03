from __future__ import annotations

import copy
import re
import subprocess
import time
from pathlib import Path

import requests


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _get_nested(data: object, dotted_key: str) -> str:
    """Traverse dict keys and list indices (e.g. data.files.0.file_url)."""
    current: object = data
    for part in dotted_key.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return ""
        if current is None:
            return ""
    return "" if current is None else str(current).strip()


def _escape_concat_path(path: Path) -> str:
    """Escape path for ffmpeg concat demuxer single-quoted form."""
    s = str(path.resolve())
    return s.replace("'", r"'\''")


def concat_mp4_files_ffmpeg(segment_paths: list[Path], output_path: Path, *, timeout_seconds: int = 600) -> None:
    """Append MP4 segments in order (stream copy). Expects compatible streams from same encoder settings."""
    if len(segment_paths) < 2:
        raise ValueError("concat needs at least 2 segment files")
    for p in segment_paths:
        if not p.is_file():
            raise FileNotFoundError(f"missing segment: {p}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = segment_paths[0].parent
    list_file = work / f"_{output_path.stem}_concat.txt"
    lines = "\n".join(f"file '{_escape_concat_path(p)}'" for p in segment_paths) + "\n"
    list_file.write_text(lines, encoding="utf-8")
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file.resolve()),
            "-c",
            "copy",
            str(output_path.resolve()),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-4000:]
            raise RuntimeError(f"ffmpeg concat failed (exit {proc.returncode}): {tail}")
    finally:
        list_file.unlink(missing_ok=True)


def generate_stitched_poyo_videos(
    *,
    api_key: str,
    base_url: str,
    generate_path: str,
    status_path_template: str,
    base_payload: dict,
    segment_count: int,
    output_path: Path,
    id_field: str = "id",
    status_field: str = "status",
    download_url_field: str = "video_url",
    ready_statuses: list[str] | None = None,
    failed_statuses: list[str] | None = None,
    poll_interval_seconds: int = 5,
    max_wait_seconds: int = 600,
) -> dict:
    """
    Run multiple PoYo/Seedance jobs (each up to API max duration, e.g. 15s) and concatenate with ffmpeg.

    Varies ``input.seed`` per segment when possible so clips are not identical.
    """
    if segment_count < 1:
        raise ValueError("segment_count must be >= 1")
    if segment_count == 1:
        return generate_and_download_poyo_video(
            api_key=api_key,
            base_url=base_url,
            generate_path=generate_path,
            status_path_template=status_path_template,
            payload=base_payload,
            output_path=output_path,
            id_field=id_field,
            status_field=status_field,
            download_url_field=download_url_field,
            ready_statuses=ready_statuses,
            failed_statuses=failed_statuses,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
        )

    work = output_path.parent / f".poyo_stitch_{re.sub(r'[^a-zA-Z0-9_-]+', '_', output_path.stem)}"
    work.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    segments_meta: list[dict] = []
    try:
        for i in range(segment_count):
            pl = copy.deepcopy(base_payload)
            inp = pl.get("input")
            if not isinstance(inp, dict):
                inp = {}
                pl["input"] = inp
            base_seed = inp.get("seed")
            if base_seed is None:
                inp["seed"] = 10_000 + i
            else:
                inp["seed"] = int(base_seed) + i

            seg_path = work / f"seg_{i:02d}.mp4"
            meta = generate_and_download_poyo_video(
                api_key=api_key,
                base_url=base_url,
                generate_path=generate_path,
                status_path_template=status_path_template,
                payload=pl,
                output_path=seg_path,
                id_field=id_field,
                status_field=status_field,
                download_url_field=download_url_field,
                ready_statuses=ready_statuses,
                failed_statuses=failed_statuses,
                poll_interval_seconds=poll_interval_seconds,
                max_wait_seconds=max_wait_seconds,
            )
            segment_paths.append(seg_path)
            segments_meta.append(meta)

        concat_mp4_files_ffmpeg(segment_paths, output_path)
    finally:
        for seg in segment_paths:
            seg.unlink(missing_ok=True)
        try:
            if work.is_dir() and not any(work.iterdir()):
                work.rmdir()
        except OSError:
            pass

    return {
        "output_path": str(output_path),
        "stitch_segments": segment_count,
        "segment_job_ids": [m.get("job_id", "") for m in segments_meta],
        "segments": segments_meta,
    }


def generate_and_download_poyo_video(
    *,
    api_key: str,
    base_url: str,
    generate_path: str,
    status_path_template: str,
    payload: dict,
    output_path: Path,
    id_field: str = "id",
    status_field: str = "status",
    download_url_field: str = "video_url",
    ready_statuses: list[str] | None = None,
    failed_statuses: list[str] | None = None,
    poll_interval_seconds: int = 5,
    max_wait_seconds: int = 600,
) -> dict:
    if not api_key.strip():
        raise RuntimeError("POYO_SEEDANCE_API_KEY is empty (legacy POYO_API_KEY also supported)")

    ready = set((ready_statuses or ["finished", "completed", "succeeded", "ready"]))
    failed = set((failed_statuses or ["failed", "error", "cancelled"]))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    start_resp = requests.post(
        _join_url(base_url, generate_path),
        json=payload,
        headers=headers,
        timeout=60,
    )
    start_resp.raise_for_status()
    start_data = start_resp.json()

    video_url = _get_nested(start_data, download_url_field)
    job_id = _get_nested(start_data, id_field)

    if not video_url:
        if not job_id:
            raise RuntimeError(f"Poyo response missing both '{id_field}' and '{download_url_field}'")
        deadline = time.time() + max_wait_seconds
        while True:
            if "{job_id}" in status_path_template:
                status_resp = requests.get(
                    _join_url(base_url, status_path_template.format(job_id=job_id)),
                    headers=headers,
                    timeout=60,
                )
            else:
                status_resp = requests.post(
                    _join_url(base_url, status_path_template),
                    json={"task_id": job_id},
                    headers=headers,
                    timeout=60,
                )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            status_value = _get_nested(status_data, status_field).lower()
            maybe_url = _get_nested(status_data, download_url_field)

            if maybe_url and status_value in ready:
                video_url = maybe_url
                break
            if status_value in failed:
                raise RuntimeError(f"Poyo generation failed with status={status_value}")
            if time.time() >= deadline:
                raise TimeoutError("Timed out waiting for Poyo video generation")

            time.sleep(poll_interval_seconds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_resp = requests.get(video_url, timeout=180)
    download_resp.raise_for_status()
    output_path.write_bytes(download_resp.content)

    return {
        "job_id": job_id,
        "video_url": video_url,
        "output_path": str(output_path),
    }
