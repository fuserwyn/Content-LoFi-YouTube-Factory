import random
from pathlib import Path

import pytest

from src.tiktok_cuts import (
    TikTokClipResult,
    _build_timeline,
    _list_tracks,
    _probe_media_duration_seconds,
    _render_one_clip,
    create_tiktok_cuts,
)


def test_create_tiktok_cuts_raises_on_missing_source(tmp_path: Path) -> None:
    source_video = tmp_path / "missing.mp4"
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    output_dir = tmp_path / "output"

    with pytest.raises(RuntimeError, match="TikTok source video not found"):
        create_tiktok_cuts(
            source_video_path=source_video,
            tracks_dir=tracks_dir,
            output_dir=output_dir,
            clips_count=3,
            clip_seconds=30,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )


def test_create_tiktok_cuts_raises_on_no_tracks(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    output_dir = tmp_path / "output"

    with pytest.raises(RuntimeError, match="No tracks available"):
        create_tiktok_cuts(
            source_video_path=source_video,
            tracks_dir=tracks_dir,
            output_dir=output_dir,
            clips_count=3,
            clip_seconds=30,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )


def test_create_tiktok_cuts_creates_output_dir(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    track = tracks_dir / "track.mp3"
    track.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    # Mock duration probing and rendering
    mocker.patch("src.tiktok_cuts._probe_media_duration_seconds", return_value=120)
    mocker.patch("src.tiktok_cuts._render_one_clip")

    assert not output_dir.exists()

    create_tiktok_cuts(
        source_video_path=source_video,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=2,
        clip_seconds=30,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    assert output_dir.exists()
    assert output_dir.is_dir()


def test_create_tiktok_cuts_probes_duration(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    track = tracks_dir / "track.mp3"
    track.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    mock_probe = mocker.patch("src.tiktok_cuts._probe_media_duration_seconds", return_value=180)
    mocker.patch("src.tiktok_cuts._render_one_clip")

    create_tiktok_cuts(
        source_video_path=source_video,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=2,
        clip_seconds=30,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    mock_probe.assert_called_once_with(source_video)


def test_create_tiktok_cuts_renders_all_clips(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    track = tracks_dir / "track.mp3"
    track.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    mocker.patch("src.tiktok_cuts._probe_media_duration_seconds", return_value=120)
    mock_render = mocker.patch("src.tiktok_cuts._render_one_clip")

    random.seed(42)
    result = create_tiktok_cuts(
        source_video_path=source_video,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=3,
        clip_seconds=30,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    assert len(result) == 3
    assert mock_render.call_count == 3


def test_create_tiktok_cuts_calls_callback(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    track = tracks_dir / "track.mp3"
    track.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    mocker.patch("src.tiktok_cuts._probe_media_duration_seconds", return_value=120)
    mocker.patch("src.tiktok_cuts._render_one_clip")

    callback_calls = []

    def callback(clip: TikTokClipResult) -> None:
        callback_calls.append(clip)

    random.seed(42)
    create_tiktok_cuts(
        source_video_path=source_video,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=2,
        clip_seconds=30,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
        on_clip_ready=callback,
    )

    assert len(callback_calls) == 2
    assert all(isinstance(clip, TikTokClipResult) for clip in callback_calls)


def test_build_timeline_fixed_count_mode() -> None:
    random.seed(42)
    timeline = _build_timeline(
        duration_seconds=120,
        clips_count=3,
        clip_seconds=30,
        clip_min_seconds=None,
        clip_max_seconds=None,
    )

    assert len(timeline) == 3
    for start, duration in timeline:
        assert start >= 0
        assert start <= 90  # 120 - 30
        assert duration == 30


def test_build_timeline_auto_mode() -> None:
    random.seed(42)
    timeline = _build_timeline(
        duration_seconds=100,
        clips_count=0,  # Auto mode
        clip_seconds=30,
        clip_min_seconds=20,
        clip_max_seconds=40,
    )

    # Should split the entire duration
    assert len(timeline) > 0
    total_duration = sum(duration for _, duration in timeline)
    assert total_duration == 100


def test_build_timeline_respects_min_max_seconds() -> None:
    random.seed(42)
    timeline = _build_timeline(
        duration_seconds=200,
        clips_count=0,  # Auto mode
        clip_seconds=30,
        clip_min_seconds=25,
        clip_max_seconds=35,
    )

    for _, duration in timeline:
        assert 25 <= duration <= 35 or duration < 25  # Last clip might be shorter


def test_build_timeline_single_clip() -> None:
    random.seed(42)
    timeline = _build_timeline(
        duration_seconds=60,
        clips_count=1,
        clip_seconds=30,
        clip_min_seconds=None,
        clip_max_seconds=None,
    )

    assert len(timeline) == 1
    start, duration = timeline[0]
    assert 0 <= start <= 30
    assert duration == 30


def test_probe_media_duration_seconds_parses_value(mocker) -> None:
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = "123.456\n"
    mocker.patch("src.tiktok_cuts.subprocess.run", return_value=mock_proc)

    duration = _probe_media_duration_seconds(Path("/fake/video.mp4"))

    assert duration == 123


def test_probe_media_duration_seconds_returns_none_on_error(mocker) -> None:
    mock_proc = mocker.Mock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mocker.patch("src.tiktok_cuts.subprocess.run", return_value=mock_proc)

    duration = _probe_media_duration_seconds(Path("/fake/video.mp4"))

    assert duration is None


def test_probe_media_duration_seconds_returns_none_on_missing_ffprobe(mocker) -> None:
    mocker.patch("src.tiktok_cuts.subprocess.run", side_effect=FileNotFoundError())

    duration = _probe_media_duration_seconds(Path("/fake/video.mp4"))

    assert duration is None


def test_probe_media_duration_seconds_returns_none_on_invalid_output(mocker) -> None:
    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = "invalid\n"
    mocker.patch("src.tiktok_cuts.subprocess.run", return_value=mock_proc)

    duration = _probe_media_duration_seconds(Path("/fake/video.mp4"))

    assert duration is None


def test_render_one_clip_builds_correct_command(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    track = tmp_path / "track.mp3"
    output = tmp_path / "output.mp4"

    mock_proc = mocker.Mock()
    mock_proc.returncode = 0
    mock_run = mocker.patch("src.tiktok_cuts.subprocess.run", return_value=mock_proc)

    _render_one_clip(
        source_video_path=source_video,
        track_path=track,
        output_path=output,
        start_second=10,
        duration_second=30,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd
    assert "10" in cmd
    assert "-t" in cmd
    assert "30" in cmd
    assert str(source_video) in cmd
    assert str(track) in cmd
    assert str(output) in cmd


def test_render_one_clip_raises_on_failure(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    track = tmp_path / "track.mp3"
    output = tmp_path / "output.mp4"

    mock_proc = mocker.Mock()
    mock_proc.returncode = 1
    mock_proc.stderr = "FFmpeg error"
    mocker.patch("src.tiktok_cuts.subprocess.run", return_value=mock_proc)

    with pytest.raises(RuntimeError, match="FFmpeg TikTok render failed"):
        _render_one_clip(
            source_video_path=source_video,
            track_path=track,
            output_path=output,
            start_second=10,
            duration_second=30,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )


def test_list_tracks_finds_audio_files(tmp_path: Path) -> None:
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()

    # Create test audio files
    (tracks_dir / "track1.mp3").write_bytes(b"audio")
    (tracks_dir / "track2.wav").write_bytes(b"audio")
    (tracks_dir / "track3.m4a").write_bytes(b"audio")
    (tracks_dir / "not_audio.txt").write_bytes(b"text")

    tracks = _list_tracks(tracks_dir)

    assert len(tracks) == 3
    assert all(track.suffix.lower() in {".mp3", ".wav", ".m4a"} for track in tracks)


def test_list_tracks_searches_recursively(tmp_path: Path) -> None:
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    subdir = tracks_dir / "subdir"
    subdir.mkdir()

    (tracks_dir / "track1.mp3").write_bytes(b"audio")
    (subdir / "track2.mp3").write_bytes(b"audio")

    tracks = _list_tracks(tracks_dir)

    assert len(tracks) == 2


def test_create_tiktok_cuts_returns_correct_structure(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    track = tracks_dir / "track.mp3"
    track.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    mocker.patch("src.tiktok_cuts._probe_media_duration_seconds", return_value=120)
    mocker.patch("src.tiktok_cuts._render_one_clip")

    random.seed(42)
    results = create_tiktok_cuts(
        source_video_path=source_video,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=2,
        clip_seconds=30,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    assert len(results) == 2
    for result in results:
        assert isinstance(result, TikTokClipResult)
        assert result.output_path.parent == output_dir
        assert result.track_path == track
        assert result.start_second >= 0
        assert result.duration_second > 0


def test_create_tiktok_cuts_raises_on_probe_failure(tmp_path: Path, mocker) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    track = tracks_dir / "track.mp3"
    track.write_bytes(b"fake audio")
    output_dir = tmp_path / "output"

    mocker.patch("src.tiktok_cuts._probe_media_duration_seconds", return_value=None)

    with pytest.raises(RuntimeError, match="Unable to probe source duration"):
        create_tiktok_cuts(
            source_video_path=source_video,
            tracks_dir=tracks_dir,
            output_dir=output_dir,
            clips_count=2,
            clip_seconds=30,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )
