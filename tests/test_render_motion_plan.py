import random
from pathlib import Path

from src.fetch_assets import ClipAsset
from src.render_video import _build_motion_plan


def _clip(clip_id: int, duration: int) -> ClipAsset:
    return ClipAsset(
        source_video_id=clip_id,
        source_url=f"https://example.com/{clip_id}",
        author_name="tester",
        download_url=f"https://example.com/dl/{clip_id}.mp4",
        local_path=Path(f"/tmp/clip_{clip_id}.mp4"),
        width=1920,
        height=1080,
        duration=duration,
        license="pexels-license",
    )


def test_motion_plan_reaches_target_duration() -> None:
    random.seed(7)
    clips = [_clip(1, 30), _clip(2, 45), _clip(3, 60)]
    plan = _build_motion_plan(
        clips=clips,
        target_duration_seconds=70,
        min_segment_seconds=6,
        max_segment_seconds=12,
    )

    total = sum(item.duration_second for item in plan)
    assert total == 70
    assert len(plan) > 1


def test_motion_plan_segment_bounds() -> None:
    random.seed(3)
    clips = [_clip(1, 10)]
    plan = _build_motion_plan(
        clips=clips,
        target_duration_seconds=8,
        min_segment_seconds=6,
        max_segment_seconds=12,
    )

    assert len(plan) >= 1
    assert sum(item.duration_second for item in plan) == 8
    for item in plan:
        assert item.start_second >= 0
        assert item.duration_second >= 1
