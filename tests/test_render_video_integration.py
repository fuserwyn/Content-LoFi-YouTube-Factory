from pathlib import Path

import pytest

from src.fetch_assets import ClipAsset
from src.render_video import RenderResult, render_video_with_ffmpeg


def _make_clip(clip_id: int, duration: int, tmp_path: Path) -> ClipAsset:
    """Helper to create a test ClipAsset."""
    local_path = tmp_path / f"clip_{clip_id}.mp4"
    local_path.write_bytes(b"fake video data")
    return ClipAsset(
        source_video_id=clip_id,
        source_url=f"https://example.com/{clip_id}",
        author_name="test_author",
        download_url=f"https://example.com/dl/{clip_id}.mp4",
        local_path=local_path,
        width=1920,
        height=1080,
        duration=duration,
        license="test-license",
    )


def test_render_video_with_ffmpeg_creates_output(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg subprocess calls
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    result = render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
    )

    assert isinstance(result, RenderResult)
    assert result.output_path == output_dir / "final.mp4"


def test_render_video_with_ffmpeg_creates_concat_list(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path), _make_clip(2, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    result = render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
    )

    assert result.concat_source_path.exists()
    concat_content = result.concat_source_path.read_text()
    assert "segment_" in concat_content


def test_render_video_with_ffmpeg_creates_stitched_video(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
    )

    # Verify FFmpeg was called multiple times (segments + stitch + final)
    assert mock_popen.call_count >= 2


def test_render_video_with_ffmpeg_loops_in_normal_mode(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    result = render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
        no_repeat_clips_in_single_video=False,
    )

    assert result.looped_stitched_video is True


def test_render_video_with_ffmpeg_no_loop_in_strict_mode(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    result = render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
        no_repeat_clips_in_single_video=True,
        allow_shorter_unique_video=True,
    )

    assert result.looped_stitched_video is False


def test_render_video_with_ffmpeg_pads_short_video(tmp_path: Path, mocker) -> None:
    # Create a short clip that won't reach target duration
    clips = [_make_clip(1, 15, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    result = render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=60,
        width=1920,
        height=1080,
        fps=30,
        no_repeat_clips_in_single_video=True,
        allow_shorter_unique_video=True,
    )

    # Short unique montage: fill length by looping stitched video, not freeze frames
    assert result.tail_padded_seconds == 0
    assert result.looped_stitched_video is True
    last_ffmpeg = mock_popen.call_args_list[-1][0][0]
    assert "-stream_loop" in last_ffmpeg
    assert "tpad" not in " ".join(last_ffmpeg)


def test_render_video_with_ffmpeg_raises_on_no_clips(tmp_path: Path) -> None:
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    with pytest.raises(RuntimeError, match="No clips available"):
        render_video_with_ffmpeg(
            clips=[],
            track_path=track_path,
            output_dir=output_dir,
            target_duration_seconds=30,
            width=1920,
            height=1080,
            fps=30,
        )


def test_render_video_with_ffmpeg_raises_on_ffmpeg_failure(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg to fail
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 1
    mock_proc.stderr = iter(["FFmpeg error\n"])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    with pytest.raises(RuntimeError, match="FFmpeg command failed"):
        render_video_with_ffmpeg(
            clips=clips,
            track_path=track_path,
            output_dir=output_dir,
            target_duration_seconds=30,
            width=1920,
            height=1080,
            fps=30,
        )


def test_render_video_with_ffmpeg_uses_correct_dimensions(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg and capture commands
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1280,
        height=720,
        fps=24,
    )

    # Check that FFmpeg was called with correct dimensions
    calls = mock_popen.call_args_list
    assert len(calls) > 0

    # At least one call should contain the dimensions
    found_dimensions = False
    for call in calls:
        cmd = call[0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        if "1280" in cmd_str and "720" in cmd_str:
            found_dimensions = True
            break

    assert found_dimensions


def test_render_video_with_ffmpeg_uses_encode_preset(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg and capture commands
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
        encode_preset="ultrafast",
        crf=18,
    )

    # Check that FFmpeg was called with correct preset
    calls = mock_popen.call_args_list
    found_preset = False
    for call in calls:
        cmd = call[0][0]
        if "ultrafast" in cmd:
            found_preset = True
            break

    assert found_preset


def test_render_video_with_ffmpeg_creates_normalized_clips(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path), _make_clip(2, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
    )

    # Verify normalized clips directory was created
    normalized_dir = output_dir / "normalized_clips"
    assert normalized_dir.exists()


def test_render_video_with_ffmpeg_returns_correct_result_structure(tmp_path: Path, mocker) -> None:
    clips = [_make_clip(1, 60, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    result = render_video_with_ffmpeg(
        clips=clips,
        track_path=track_path,
        output_dir=output_dir,
        target_duration_seconds=30,
        width=1920,
        height=1080,
        fps=30,
    )

    assert isinstance(result, RenderResult)
    assert result.output_path.name == "final.mp4"
    assert result.concat_source_path.name == "concat_list.txt"
    assert result.planned_seconds > 0
    assert result.final_target_seconds == 30
    assert isinstance(result.looped_stitched_video, bool)
    assert result.tail_padded_seconds >= 0


def test_render_video_with_ffmpeg_strict_mode_insufficient_clips(tmp_path: Path, mocker) -> None:
    # Create clips that don't have enough unique footage
    clips = [_make_clip(1, 10, tmp_path)]
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock FFmpeg
    mock_popen = mocker.patch("src.render_video.subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stderr = iter([])
    mock_proc.wait = mocker.Mock()
    mock_popen.return_value = mock_proc

    with pytest.raises(RuntimeError, match="Unable to build a valid render plan"):
        render_video_with_ffmpeg(
            clips=clips,
            track_path=track_path,
            output_dir=output_dir,
            target_duration_seconds=60,
            width=1920,
            height=1080,
            fps=30,
            no_repeat_clips_in_single_video=True,
            allow_shorter_unique_video=False,
        )
