"""MiniMax (Hailuo) video generation — direct api.minimax.io, async task + poll + file retrieve."""

from __future__ import annotations

import copy
import re
import time
from pathlib import Path
from typing import Any

import requests


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def minimax_t2v_body_from_payload(
    payload: dict,
    *,
    default_model: str,
    default_duration: int,
    default_resolution: str,
) -> dict[str, Any]:
    """Build POST /v1/video_generation JSON from legacy PoYo/Seedance-shaped or flat MiniMax-shaped body."""
    mm: dict[str, Any] = {}
    if isinstance(payload.get("minimax"), dict):
        mm = payload["minimax"]

    inp = payload.get("input") if isinstance(payload.get("input"), dict) else {}

    prompt = ""
    if isinstance(payload.get("prompt"), str) and payload["prompt"].strip():
        prompt = payload["prompt"].strip()
    elif isinstance(inp.get("prompt"), str) and inp["prompt"].strip():
        prompt = inp["prompt"].strip()

    def _pick_minimax_model(*candidates: object) -> str:
        for p in candidates:
            if not isinstance(p, str):
                continue
            s = p.strip()
            if s.startswith("MiniMax-") or s.startswith("T2V-"):
                return s
        return default_model

    model = _pick_minimax_model(
        mm.get("model"),
        payload.get("model"),
        inp.get("model"),
    )
    duration_raw = mm.get("duration", payload.get("duration", inp.get("duration", default_duration)))
    try:
        duration = int(duration_raw)
    except (TypeError, ValueError):
        duration = default_duration

    resolution_raw = (
        mm.get("resolution")
        or payload.get("resolution")
        or inp.get("resolution")
        or default_resolution
    )
    r = str(resolution_raw).strip().upper() if resolution_raw else ""
    if r.endswith("P") and r[:-1].replace(".", "").isdigit():
        resolution = r
    elif r.isdigit():
        resolution = f"{r}P"
    elif r:
        resolution = r if r.endswith("P") else f"{r}P"
    else:
        resolution = default_resolution

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
    }
    # Optional MiniMax fields if present on payload
    if "prompt_optimizer" in mm:
        body["prompt_optimizer"] = bool(mm["prompt_optimizer"])
    elif "prompt_optimizer" in payload:
        body["prompt_optimizer"] = bool(payload["prompt_optimizer"])
    if "fast_pretreatment" in mm:
        body["fast_pretreatment"] = bool(mm["fast_pretreatment"])
    elif "fast_pretreatment" in payload:
        body["fast_pretreatment"] = bool(payload["fast_pretreatment"])
    if isinstance(mm.get("callback_url"), str):
        body["callback_url"] = mm["callback_url"]

    return body


def generate_and_download_minimax_video(
    *,
    api_key: str,
    base_url: str,
    payload: dict,
    output_path: Path,
    default_model: str,
    default_duration: int,
    default_resolution: str,
    poll_interval_seconds: int = 10,
    max_wait_seconds: int = 600,
) -> dict:
    if not api_key.strip():
        raise RuntimeError("MINIMAX_API_KEY is empty")

    body = minimax_t2v_body_from_payload(
        payload,
        default_model=default_model,
        default_duration=default_duration,
        default_resolution=default_resolution,
    )
    if not body.get("prompt"):
        raise RuntimeError("MiniMax video: empty prompt (set prompt on payload or input.prompt)")

    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    start_url = _join_url(base_url, "/v1/video_generation")
    start_resp = requests.post(start_url, json=body, headers=headers, timeout=120)
    start_resp.raise_for_status()
    start_data = start_resp.json()

    base_resp = start_data.get("base_resp") if isinstance(start_data.get("base_resp"), dict) else {}
    code = base_resp.get("status_code")
    if code not in (None, 0):
        msg = base_resp.get("status_msg", start_data)
        raise RuntimeError(f"MiniMax video_generation rejected: {msg}")

    task_id = start_data.get("task_id")
    if not task_id:
        raise RuntimeError(f"MiniMax response missing task_id: {start_data}")

    query_url = _join_url(base_url, "/v1/query/video_generation")
    deadline = time.time() + max_wait_seconds
    file_id: str | None = None
    poll = max(5, poll_interval_seconds)

    while True:
        q = requests.get(query_url, headers=headers, params={"task_id": task_id}, timeout=60)
        q.raise_for_status()
        data = q.json()
        status_raw = data.get("status")
        status = str(status_raw).strip().lower() if status_raw is not None else ""

        if status in ("success", "succeeded"):
            file_id = data.get("file_id") or data.get("fileId")
            if file_id:
                break
        if status in ("fail", "failed", "error"):
            err = data.get("error_message") or data.get("message") or data
            raise RuntimeError(f"MiniMax generation failed: {err}")

        if time.time() >= deadline:
            raise TimeoutError("Timed out waiting for MiniMax video generation")

        time.sleep(poll)

    retrieve_url = _join_url(base_url, "/v1/files/retrieve")
    fr = requests.get(retrieve_url, headers=headers, params={"file_id": file_id}, timeout=60)
    fr.raise_for_status()
    fr_data = fr.json()
    file_obj = fr_data.get("file") if isinstance(fr_data.get("file"), dict) else {}
    download_url = file_obj.get("download_url") or file_obj.get("downloadUrl")
    if not download_url:
        raise RuntimeError(f"MiniMax files/retrieve missing download_url: {fr_data}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dl = requests.get(str(download_url), timeout=300)
    dl.raise_for_status()
    output_path.write_bytes(dl.content)

    return {
        "job_id": str(task_id),
        "file_id": str(file_id),
        "output_path": str(output_path),
    }


def generate_stitched_minimax_videos(
    *,
    api_key: str,
    base_url: str,
    base_payload: dict,
    segment_count: int,
    output_path: Path,
    default_model: str,
    default_duration: int,
    default_resolution: str,
    poll_interval_seconds: int = 10,
    max_wait_seconds: int = 600,
) -> dict:
    if segment_count < 1:
        raise ValueError("segment_count must be >= 1")
    if segment_count == 1:
        return generate_and_download_minimax_video(
            api_key=api_key,
            base_url=base_url,
            payload=base_payload,
            output_path=output_path,
            default_model=default_model,
            default_duration=default_duration,
            default_resolution=default_resolution,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
        )

    work = output_path.parent / f".minimax_stitch_{re.sub(r'[^a-zA-Z0-9_-]+', '_', output_path.stem)}"
    work.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    segments_meta: list[dict] = []
    try:
        from .poyo_video import concat_mp4_files_ffmpeg

        for i in range(segment_count):
            pl = copy.deepcopy(base_payload)
            base_prompt_info = minimax_t2v_body_from_payload(
                pl,
                default_model=default_model,
                default_duration=default_duration,
                default_resolution=default_resolution,
            )
            prompt = str(base_prompt_info.get("prompt") or "")
            if i > 0:
                prompt = f"{prompt} [continuous shot segment {i + 1} of {segment_count}]"
            if isinstance(pl.get("input"), dict):
                inp2 = dict(pl["input"])
                inp2["prompt"] = prompt
                pl["input"] = inp2
            else:
                pl["prompt"] = prompt

            seg_path = work / f"seg_{i:02d}.mp4"
            meta = generate_and_download_minimax_video(
                api_key=api_key,
                base_url=base_url,
                payload=pl,
                output_path=seg_path,
                default_model=default_model,
                default_duration=default_duration,
                default_resolution=default_resolution,
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
