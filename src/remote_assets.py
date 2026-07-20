"""Sync background videos and music tracks from S3-compatible storage (AWS S3 / Cloudflare R2).

Videos: list the bucket, download only the next unused batch (default 5), grow the batch
until unique footage covers the track, then delete locals after publish while keeping DB markers.
Tracks: still mirrored into assets/tracks as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging

from .fetch_assets import LOCAL_VIDEO_EXTENSIONS, ClipAsset, _probe_video
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


@dataclass(frozen=True)
class RemoteObject:
    key: str
    filename: str
    size: int


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


def used_clip_filenames(used_clip_urls: set[str] | list[str]) -> set[str]:
    """Normalize DB markers (full path or bare name) to filenames."""
    return {Path(u).name for u in used_clip_urls if u}


def list_prefix_objects(
    client,
    bucket: str,
    prefix: str,
    allowed_suffixes: set[str] | None = None,
) -> list[RemoteObject]:
    """List remote objects under ``prefix``, flattened by filename, stable-sorted by key."""
    norm_prefix = prefix.strip("/")
    list_prefix = f"{norm_prefix}/" if norm_prefix else ""
    found: list[RemoteObject] = []
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
            found.append(RemoteObject(key=key, filename=filename, size=int(obj.get("Size") or 0)))
    found.sort(key=lambda o: o.key)
    return found


def sync_prefix(
    client,
    bucket: str,
    prefix: str,
    dest_dir: Path,
    allowed_suffixes: set[str] | None = None,
    *,
    skip_filenames: set[str] | None = None,
    max_downloads: int | None = None,
) -> list[Path]:
    """Download objects under ``prefix`` into ``dest_dir`` (flattened to filename).

    Skips objects whose local file already exists with the same size, and optionally skips
    filenames in ``skip_filenames``. When ``max_downloads`` is set, stops after that many
    new downloads (already-present matching files do not count).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    skip = skip_filenames or set()
    downloaded: list[Path] = []

    for obj in list_prefix_objects(client, bucket, prefix, allowed_suffixes):
        if obj.filename in skip:
            continue

        dest = dest_dir / obj.filename
        if dest.exists() and dest.stat().st_size == obj.size:
            continue

        if max_downloads is not None and len(downloaded) >= max_downloads:
            break

        LOGGER.info("REMOTE_SYNC: downloading s3://%s/%s -> %s", bucket, obj.key, dest)
        client.download_file(bucket, obj.key, str(dest))
        downloaded.append(dest)

    return downloaded


def build_source_video_queue(
    remote: list[RemoteObject],
    used_filenames: set[str],
) -> tuple[list[RemoteObject], bool]:
    """Build download order: unused first (stable), then wrap from the start of the library.

    Returns (queue, started_new_cycle). ``started_new_cycle`` is True when every remote
    file was already marked — caller should clear markers and treat this as a fresh cycle.
    """
    if not remote:
        return [], False

    unused = [o for o in remote if o.filename not in used_filenames]
    if not unused:
        # Full wrap: start again from the beginning of the library.
        return list(remote), True

    queue: list[RemoteObject] = list(unused)
    seen = {o.filename for o in queue}
    for o in remote:
        if o.filename in seen:
            continue
        queue.append(o)
        seen.add(o.filename)
    return queue, False


def download_source_video_batch(
    client,
    bucket: str,
    prefix: str,
    dest_dir: Path,
    *,
    used_filenames: set[str],
    batch_size: int,
    min_total_seconds: float,
    min_clip_seconds: int,
    min_width: int,
    min_height: int,
) -> tuple[list[ClipAsset], list[str], bool]:
    """List S3 videos, download the next unused batch, grow until track duration is covered.

    Returns (clips, marker_filenames, started_new_cycle).
    Markers are bare filenames for stable DB identity across hosts.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    remote = list_prefix_objects(client, bucket, prefix, LOCAL_VIDEO_EXTENSIONS)
    if not remote:
        LOGGER.warning("REMOTE_SYNC: no source videos under s3://%s/%s", bucket, prefix)
        return [], [], False

    queue, started_new_cycle = build_source_video_queue(remote, used_filenames)
    if started_new_cycle:
        LOGGER.info(
            "REMOTE_SYNC: all %d remote videos were marked used; starting new cycle from the beginning",
            len(remote),
        )

    batch_size = max(1, batch_size)
    clips: list[ClipAsset] = []
    total_seconds = 0.0
    marker_names: list[str] = []

    for index, obj in enumerate(queue):
        have_min_count = len(clips) >= min(batch_size, len(remote))
        if have_min_count and total_seconds >= min_total_seconds:
            break

        dest = dest_dir / obj.filename
        if not (dest.exists() and dest.stat().st_size == obj.size):
            LOGGER.info("REMOTE_SYNC: downloading s3://%s/%s -> %s", bucket, obj.key, dest)
            client.download_file(bucket, obj.key, str(dest))
        else:
            LOGGER.info("REMOTE_SYNC: reusing local %s", dest)

        metadata = _probe_video(dest)
        if not metadata:
            LOGGER.warning("REMOTE_SYNC: ffprobe failed for %s; skipping", dest)
            dest.unlink(missing_ok=True)
            continue
        if metadata["duration"] < min_clip_seconds:
            LOGGER.warning("REMOTE_SYNC: too short (%ss) %s; skipping", metadata["duration"], dest)
            dest.unlink(missing_ok=True)
            continue
        if metadata["width"] < min_width or metadata["height"] < min_height:
            LOGGER.warning(
                "REMOTE_SYNC: resolution %sx%s below %sx%s for %s; skipping",
                metadata["width"],
                metadata["height"],
                min_width,
                min_height,
                dest,
            )
            dest.unlink(missing_ok=True)
            continue
        if metadata["width"] < metadata["height"]:
            LOGGER.warning("REMOTE_SYNC: portrait clip skipped %s", dest)
            dest.unlink(missing_ok=True)
            continue

        clips.append(
            ClipAsset(
                source_video_id=index + 1,
                source_url=obj.filename,
                author_name="local",
                download_url=f"s3://{bucket}/{obj.key}",
                local_path=dest,
                width=metadata["width"],
                height=metadata["height"],
                duration=metadata["duration"],
                license="local-owner",
            )
        )
        marker_names.append(obj.filename)
        total_seconds += float(metadata["duration"])
        LOGGER.info(
            "REMOTE_SYNC: batch clip %d/%s +%ss (total=%.1fs need=%.1fs) file=%s",
            len(clips),
            batch_size,
            metadata["duration"],
            total_seconds,
            min_total_seconds,
            obj.filename,
        )

    if clips and total_seconds < min_total_seconds:
        LOGGER.warning(
            "REMOTE_SYNC: unique footage still short after batch (have=%.1fs need=%.1fs clips=%d)",
            total_seconds,
            min_total_seconds,
            len(clips),
        )

    return clips, marker_names, started_new_cycle


def delete_local_source_videos(clips: list[ClipAsset], videos_dir: Path) -> int:
    """Delete downloaded source files after publish; DB markers stay."""
    deleted = 0
    videos_dir = videos_dir.resolve()
    for clip in clips:
        path = Path(clip.local_path)
        try:
            if path.resolve().parent != videos_dir:
                continue
        except OSError:
            if path.parent.resolve() != videos_dir:
                continue
        if path.is_file():
            path.unlink(missing_ok=True)
            deleted += 1
            LOGGER.info("CLEANUP: deleted local source video %s", path)
    return deleted


def sync_assets(
    cfg: S3SyncConfig,
    *,
    videos_dir: Path,
    tracks_dir: Path,
    client=None,
    include_videos: bool = True,
    include_tracks: bool = True,
    skip_video_filenames: set[str] | None = None,
    max_video_downloads: int | None = None,
) -> dict[str, list[Path]]:
    """Pull source videos and/or tracks from the bucket into local asset dirs.

    Prefer ``download_source_video_batch`` for render runs. This helper remains for
    tracks sync and tests / full mirrors.
    """
    if not cfg.enabled:
        LOGGER.info("REMOTE_SYNC: disabled (ASSETS_SYNC_ENABLED=false); using local files only")
        return {"videos": [], "tracks": []}

    if not cfg.bucket:
        raise ValueError("ASSETS_SYNC_ENABLED=true but ASSETS_S3_BUCKET is empty")

    if client is None:
        client = build_s3_client(cfg)

    videos: list[Path] = []
    if include_videos:
        videos = sync_prefix(
            client,
            bucket=cfg.bucket,
            prefix=cfg.videos_prefix,
            dest_dir=videos_dir,
            allowed_suffixes=LOCAL_VIDEO_EXTENSIONS,
            skip_filenames=skip_video_filenames,
            max_downloads=max_video_downloads,
        )
    tracks: list[Path] = []
    if include_tracks:
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
