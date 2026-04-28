from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import time
import requests


PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


@dataclass
class ClipAsset:
    source_video_id: int
    source_url: str
    author_name: str
    download_url: str
    local_path: Path
    width: int
    height: int
    duration: int
    license: str


def _choose_file(video_files: list[dict], min_width: int, min_height: int) -> dict | None:
    suitable = [
        vf
        for vf in video_files
        if vf.get("width", 0) >= min_width
        and vf.get("height", 0) >= min_height
        and vf.get("width", 0) >= vf.get("height", 0)
    ]
    if not suitable:
        return None
    return sorted(suitable, key=lambda x: (x.get("width", 0), x.get("height", 0)), reverse=True)[0]


def fetch_and_download_clips(
    api_key: str,
    tags: list[str],
    output_dir: Path,
    max_clips: int,
    min_clip_seconds: int,
    min_width: int,
    min_height: int,
    recently_used_clip_urls: set[str],
    per_page: int = 30,
    pages_per_tag: int = 2,
) -> list[ClipAsset]:
    headers = {"Authorization": api_key}
    candidates: list[dict] = []

    for tag in tags:
        for page in range(1, pages_per_tag + 1):
            params = {"query": tag, "per_page": per_page, "page": page}
            payload = _request_with_retry(headers=headers, params=params)
            candidates.extend(payload.get("videos", []))

    random.shuffle(candidates)
    selected: list[ClipAsset] = []

    for video in candidates:
        if len(selected) >= max_clips:
            break

        duration = int(video.get("duration", 0))
        if duration < min_clip_seconds:
            continue

        source_url = video.get("url", "")
        if not source_url or source_url in recently_used_clip_urls:
            continue

        chosen_file = _choose_file(video.get("video_files", []), min_width=min_width, min_height=min_height)
        if not chosen_file:
            continue

        download_url = chosen_file.get("link")
        if not download_url:
            continue

        clip_filename = f"clip_{video.get('id')}.mp4"
        local_path = output_dir / clip_filename

        try:
            _download_file(download_url, local_path)
        except requests.RequestException:
            continue

        selected.append(
            ClipAsset(
                source_video_id=int(video.get("id")),
                source_url=source_url,
                author_name=(video.get("user") or {}).get("name", "unknown"),
                download_url=download_url,
                local_path=local_path,
                width=int(chosen_file.get("width", 0)),
                height=int(chosen_file.get("height", 0)),
                duration=duration,
                license="pexels-license",
            )
        )

    return selected


def _download_file(url: str, destination: Path) -> None:
    with requests.get(url, timeout=120, stream=True) as response:
        response.raise_for_status()
        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)


def _request_with_retry(headers: dict, params: dict, max_attempts: int = 3) -> dict:
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=45)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt >= max_attempts:
                raise
            time.sleep(delay)
            delay *= 2

    return {}
