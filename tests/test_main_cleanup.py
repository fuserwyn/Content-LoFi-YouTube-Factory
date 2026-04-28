from pathlib import Path

from src.main import _cleanup_temp_files


def test_cleanup_temp_files_removes_temp_data(tmp_path: Path) -> None:
    clips = tmp_path / "clips"
    renders = tmp_path / "renders"
    nested = renders / "normalized_clips"
    clips.mkdir()
    renders.mkdir()
    nested.mkdir()

    (clips / "clip1.mp4").write_text("x", encoding="utf-8")
    (renders / "stitched.mp4").write_text("x", encoding="utf-8")
    (nested / "segment_001.mp4").write_text("x", encoding="utf-8")
    (renders / "final.mp4").write_text("x", encoding="utf-8")

    _cleanup_temp_files(clips, renders, keep_final_output=True)

    assert not (clips / "clip1.mp4").exists()
    assert not (renders / "stitched.mp4").exists()
    assert not nested.exists()
    assert (renders / "final.mp4").exists()
