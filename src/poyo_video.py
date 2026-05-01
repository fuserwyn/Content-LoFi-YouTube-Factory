from __future__ import annotations

from pathlib import Path
import time

import requests


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


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
        raise RuntimeError("POYO_API_KEY is empty")

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

    video_url = str(start_data.get(download_url_field, "")).strip()
    job_id = str(start_data.get(id_field, "")).strip()

    if not video_url:
        if not job_id:
            raise RuntimeError(f"Poyo response missing both '{id_field}' and '{download_url_field}'")
        deadline = time.time() + max_wait_seconds
        while True:
            status_resp = requests.get(
                _join_url(base_url, status_path_template.format(job_id=job_id)),
                headers=headers,
                timeout=60,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            status_value = str(status_data.get(status_field, "")).strip().lower()
            maybe_url = str(status_data.get(download_url_field, "")).strip()

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
