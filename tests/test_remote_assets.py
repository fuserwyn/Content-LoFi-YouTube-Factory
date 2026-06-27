from pathlib import Path

import pytest

from src.remote_assets import S3SyncConfig, sync_assets, sync_prefix


class FakeS3Client:
    """Minimal stand-in for a boto3 S3 client: serves objects from an in-memory map."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.downloads: list[str] = []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket: str, Prefix: str):  # noqa: N803 (boto3 kwarg names)
        contents = [
            {"Key": key, "Size": len(data)}
            for key, data in self.objects.items()
            if key.startswith(Prefix)
        ]
        yield {"Contents": contents}

    def download_file(self, Bucket: str, Key: str, Filename: str):  # noqa: N803
        self.downloads.append(Key)
        Path(Filename).write_bytes(self.objects[Key])


def _cfg(**overrides) -> S3SyncConfig:
    base = dict(
        enabled=True,
        bucket="bucket",
        endpoint_url="",
        region="auto",
        access_key_id="k",
        secret_access_key="s",
        videos_prefix="source_videos",
        tracks_prefix="tracks",
    )
    base.update(overrides)
    return S3SyncConfig(**base)


def test_sync_prefix_downloads_matching_files_and_flattens(tmp_path: Path) -> None:
    client = FakeS3Client(
        {
            "source_videos/a.mp4": b"video-a",
            "source_videos/nested/b.mov": b"video-b",
            "source_videos/notes.txt": b"skip-me",
            "tracks/song.mp3": b"track",
        }
    )
    dest = tmp_path / "videos"

    downloaded = sync_prefix(
        client,
        bucket="bucket",
        prefix="source_videos",
        dest_dir=dest,
        allowed_suffixes={".mp4", ".mov"},
    )

    names = sorted(p.name for p in downloaded)
    assert names == ["a.mp4", "b.mov"]
    assert (dest / "a.mp4").read_bytes() == b"video-a"
    assert not (dest / "notes.txt").exists()


def test_sync_prefix_skips_existing_same_size(tmp_path: Path) -> None:
    client = FakeS3Client({"tracks/song.mp3": b"track"})
    dest = tmp_path / "tracks"
    dest.mkdir()
    (dest / "song.mp3").write_bytes(b"track")  # already present, same size

    downloaded = sync_prefix(
        client, bucket="bucket", prefix="tracks", dest_dir=dest, allowed_suffixes={".mp3"}
    )

    assert downloaded == []
    assert client.downloads == []


def test_sync_assets_pulls_videos_and_tracks(tmp_path: Path) -> None:
    client = FakeS3Client(
        {
            "source_videos/clip.mp4": b"clip",
            "tracks/song.mp3": b"track",
        }
    )
    videos_dir = tmp_path / "v"
    tracks_dir = tmp_path / "t"

    result = sync_assets(_cfg(), videos_dir=videos_dir, tracks_dir=tracks_dir, client=client)

    assert [p.name for p in result["videos"]] == ["clip.mp4"]
    assert [p.name for p in result["tracks"]] == ["song.mp3"]


def test_sync_assets_tracks_only_skips_videos(tmp_path: Path) -> None:
    client = FakeS3Client(
        {
            "source_videos/clip.mp4": b"clip",
            "tracks/song.mp3": b"track",
        }
    )
    videos_dir = tmp_path / "v"
    tracks_dir = tmp_path / "t"

    result = sync_assets(
        _cfg(),
        videos_dir=videos_dir,
        tracks_dir=tracks_dir,
        client=client,
        include_videos=False,
    )

    assert result["videos"] == []
    assert [p.name for p in result["tracks"]] == ["song.mp3"]
    assert "source_videos/clip.mp4" not in client.downloads


def test_sync_assets_disabled_is_noop(tmp_path: Path) -> None:
    client = FakeS3Client({"tracks/song.mp3": b"track"})
    result = sync_assets(
        _cfg(enabled=False), videos_dir=tmp_path / "v", tracks_dir=tmp_path / "t", client=client
    )
    assert result == {"videos": [], "tracks": []}
    assert client.downloads == []


def test_sync_assets_requires_bucket(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ASSETS_S3_BUCKET"):
        sync_assets(
            _cfg(bucket=""),
            videos_dir=tmp_path / "v",
            tracks_dir=tmp_path / "t",
            client=FakeS3Client({}),
        )
