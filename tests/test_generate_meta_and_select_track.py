from pathlib import Path

from src.generate_meta import generate_metadata
from src.select_track import choose_track


def test_generate_metadata_has_required_fields() -> None:
    track = Path("assets/tracks/night_wave_01.mp3")
    meta = generate_metadata(track, ["ocean", "sunset", "lofi"])

    assert "night wave 01" in meta.title.lower()
    assert "Track: night wave 01" in meta.description
    assert len(meta.tags) <= 15
    assert "lofi" in meta.tags


def test_choose_track_prefers_non_recent(tmp_path: Path) -> None:
    first = tmp_path / "a.mp3"
    second = tmp_path / "b.mp3"
    first.write_text("x", encoding="utf-8")
    second.write_text("y", encoding="utf-8")

    picked = choose_track(tmp_path, recently_used_tracks={str(first)})
    assert picked == second


def test_choose_track_raises_if_empty(tmp_path: Path) -> None:
    try:
        choose_track(tmp_path, recently_used_tracks=set())
        raise AssertionError("Expected RuntimeError for empty tracks folder")
    except RuntimeError as exc:
        assert "No tracks found" in str(exc)
