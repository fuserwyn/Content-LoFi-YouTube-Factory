from __future__ import annotations

from pathlib import Path
import time

import requests


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _get_nested(data: dict, dotted_key: str) -> str:
    current = data
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return "" if current is None else str(current).strip()


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

    ready = set((ready_statuses or ["completed", "succeeded", "ready"]))
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
