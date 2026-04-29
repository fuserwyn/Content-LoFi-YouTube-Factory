from pathlib import Path

from src.fetch_assets import _probe_video, load_local_clips


def test_probe_video_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert _probe_video(tmp_path / "missing.mp4") is None


def test_load_local_clips_skips_unprobeable_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    fake = source / "a.mp4"
    fake.write_text("not-a-video", encoding="utf-8")

    clips = load_local_clips(
        source_dir=source,
        max_clips=10,
        min_clip_seconds=3,
        min_width=1280,
        min_height=720,
        recently_used_clip_urls=set(),
    )
    assert clips == []
