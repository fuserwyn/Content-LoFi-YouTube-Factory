"""Sync background videos and music tracks from S3-compatible storage (AWS S3 / Cloudflare R2).

Files live in a bucket instead of the Docker image, so the library can grow without
bloating builds. Before each render we pull any missing objects into the local asset
dirs; ``load_local_clips`` / ``choose_track`` then read them as usual.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging

from .fetch_assets import LOCAL_VIDEO_EXTENSIONS
from .select_track import SUPPORTED_EXTENSIONS as TRACK_EXTENSIONS


LOGGER = logging.getLogger("content_factory")


@dataclass(frozen=True)
class S3SyncConfig:
    enabled: bool
    bucket: str
    endpoint_url: str
    region: str
    access_key_id: str
    secret_access_key: str
    videos_prefix: str
    tracks_prefix: str


def build_s3_client(cfg: S3SyncConfig):
    """Create a boto3 S3 client. Imported lazily so envs without boto3 still load config/tests."""
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url or None,
        region_name=cfg.region or None,
        aws_access_key_id=cfg.access_key_id or None,
        aws_secret_access_key=cfg.secret_access_key or None,
        config=BotoConfig(signature_version="s3v4"),
    )


def sync_prefix(
    client,
    bucket: str,
    prefix: str,
    dest_dir: Path,
    allowed_suffixes: set[str] | None = None,
) -> list[Path]:
    """Download every object under ``prefix`` into ``dest_dir`` (flattened to filename).

    Skips objects whose local file already exists with the same size, so re-runs are cheap
    (only a bucket listing) and only newly added files are fetched.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    norm_prefix = prefix.strip("/")
    list_prefix = f"{norm_prefix}/" if norm_prefix else ""

    downloaded: list[Path] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            if not key or key.endswith("/"):
                continue
            filename = Path(key).name
            if not filename:
                continue
            if allowed_suffixes is not None and Path(filename).suffix.lower() not in allowed_suffixes:
                continue

            dest = dest_dir / filename
            remote_size = obj.get("Size")
            if dest.exists() and remote_size is not None and dest.stat().st_size == remote_size:
                continue

            LOGGER.info("REMOTE_SYNC: downloading s3://%s/%s -> %s", bucket, key, dest)
            client.download_file(bucket, key, str(dest))
            downloaded.append(dest)

    return downloaded


def sync_assets(
    cfg: S3SyncConfig,
    *,
    videos_dir: Path,
    tracks_dir: Path,
    client=None,
) -> dict[str, list[Path]]:
    """Pull source videos and tracks from the bucket into local asset dirs.

    No-op (returns empties) when sync is disabled. Failures are logged and re-raised by the
    caller's discretion; here we surface them so a misconfigured bucket fails loudly.
    """
    if not cfg.enabled:
        LOGGER.info("REMOTE_SYNC: disabled (ASSETS_SYNC_ENABLED=false); using local files only")
        return {"videos": [], "tracks": []}

    if not cfg.bucket:
        raise ValueError("ASSETS_SYNC_ENABLED=true but ASSETS_S3_BUCKET is empty")

    if client is None:
        client = build_s3_client(cfg)

    videos = sync_prefix(
        client,
        bucket=cfg.bucket,
        prefix=cfg.videos_prefix,
        dest_dir=videos_dir,
        allowed_suffixes=LOCAL_VIDEO_EXTENSIONS,
    )
    tracks = sync_prefix(
        client,
        bucket=cfg.bucket,
        prefix=cfg.tracks_prefix,
        dest_dir=tracks_dir,
        allowed_suffixes=TRACK_EXTENSIONS,
    )
    LOGGER.info(
        "REMOTE_SYNC: complete bucket=%s new_videos=%d new_tracks=%d",
        cfg.bucket,
        len(videos),
        len(tracks),
    )
    return {"videos": videos, "tracks": tracks}
