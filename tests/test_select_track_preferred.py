from pathlib import Path

from src.select_track import choose_track
from src.select_track import SUPPORTED_EXTENSIONS


def _make_track(path: Path) -> None:
    path.write_text("x", encoding="utf-8")


def test_choose_track_prefers_preferred_track_even_if_recent_when_allowed(tmp_path: Path) -> None:
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    _make_track(a)
    _make_track(b)

    picked = choose_track(
        tracks_dir=tmp_path,
        recently_used_tracks={str(a)},
        preferred_track="a.mp3",
        allow_recent_preferred=True,
    )
    assert picked == a


def test_choose_track_prefers_preferred_track_only_if_not_recent(tmp_path: Path) -> None:
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    _make_track(a)
    _make_track(b)

    picked = choose_track(
        tracks_dir=tmp_path,
        recently_used_tracks={str(a)},
        preferred_track="a.mp3",
        allow_recent_preferred=False,
    )
    # Falls back to non-recent pool (b) deterministically in this small case.
    assert picked == b


def test_choose_track_prefers_by_absolute_path(tmp_path: Path) -> None:
    a = tmp_path / "a.mp3"
    _make_track(a)

    picked = choose_track(
        tracks_dir=tmp_path,
        recently_used_tracks=set(),
        preferred_track=str(a),
    )
    assert picked == a

