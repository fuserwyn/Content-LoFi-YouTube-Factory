from pathlib import Path

import pytest

from src.generate_images import GeneratedImage
from src.render_images import ImageRenderResult, _run_ffmpeg, render_video_from_images


def _make_image(index: int, tmp_path: Path) -> GeneratedImage:
    """Helper to create a test GeneratedImage."""
    image_path = tmp_path / f"scene_{index:03d}.jpg"
    image_path.write_bytes(b"fake image data")
    return GeneratedImage(
        scene_index=index,
        prompt=f"test prompt {index}",
        local_path=image_path,
    )


def test_render_video_from_images_creates_concat_file(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path), _make_image(1, tmp_path)]

    # Mock FFmpeg execution
    mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    result = render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    assert result.concat_source_path.exists()
    concat_content = result.concat_source_path.read_text()
    assert "scene_000.jpg" in concat_content
    assert "scene_001.jpg" in concat_content


def test_render_video_from_images_includes_all_images(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(i, tmp_path) for i in range(3)]

    # Mock FFmpeg execution
    mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    result = render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=15,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    concat_content = result.concat_source_path.read_text()
    lines = concat_content.strip().split("\n")
    # Each image appears twice: file line + duration line, plus final duplicate
    assert len(lines) == 7  # 3 * 2 + 1 final file line


def test_render_video_from_images_sets_scene_duration(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path)]

    # Mock FFmpeg execution
    mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=7,
        encode_preset="veryfast",
        crf=23,
    )

    concat_path = output_dir / "images_concat.txt"
    concat_content = concat_path.read_text()
    assert "duration 7" in concat_content


def test_render_video_from_images_duplicates_last_frame(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path), _make_image(1, tmp_path)]

    # Mock FFmpeg execution
    mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    concat_path = output_dir / "images_concat.txt"
    concat_content = concat_path.read_text()
    lines = concat_content.strip().split("\n")
    # Last line should be the final image without duration
    assert "scene_001.jpg" in lines[-1]
    assert "duration" not in lines[-1]


def test_render_video_from_images_builds_correct_ffmpeg_command(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path)]

    # Mock FFmpeg execution and capture the command
    mock_run = mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    # Check that FFmpeg was called
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-f" in cmd
    assert "concat" in cmd
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "-preset" in cmd
    assert "veryfast" in cmd
    assert "-crf" in cmd
    assert "23" in cmd


def test_render_video_from_images_applies_zoompan_filter(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path)]

    # Mock FFmpeg execution and capture the command
    mock_run = mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    cmd = mock_run.call_args[0][0]
    vf_index = cmd.index("-vf")
    vf_value = cmd[vf_index + 1]
    assert "zoompan" in vf_value
    assert "1920x1080" in vf_value
    assert "fps=30" in vf_value


def test_render_video_from_images_mixes_audio(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path)]

    # Mock FFmpeg execution and capture the command
    mock_run = mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    cmd = mock_run.call_args[0][0]
    # Check that track is included as input
    assert str(track_path) in cmd
    # Check audio codec
    assert "-c:a" in cmd
    assert "aac" in cmd


def test_render_video_from_images_raises_on_empty_images(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    with pytest.raises(RuntimeError, match="No generated images"):
        render_video_from_images(
            images=[],
            track_path=track_path,
            output_dir=output_dir,
            width=1920,
            height=1080,
            fps=30,
            target_duration_seconds=10,
            scene_seconds=5,
            encode_preset="veryfast",
            crf=23,
        )


def test_render_video_from_images_raises_on_ffmpeg_failure(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path)]

    # Mock FFmpeg to fail
    mocker.patch(
        "src.render_images.subprocess.run",
        return_value=mocker.Mock(returncode=1, stderr="FFmpeg error"),
    )

    with pytest.raises(RuntimeError, match="FFmpeg command failed"):
        render_video_from_images(
            images=images,
            track_path=track_path,
            output_dir=output_dir,
            width=1920,
            height=1080,
            fps=30,
            target_duration_seconds=10,
            scene_seconds=5,
            encode_preset="veryfast",
            crf=23,
        )


def test_run_ffmpeg_raises_on_nonzero_exit(mocker) -> None:
    # Mock subprocess to return non-zero exit code
    mocker.patch(
        "src.render_images.subprocess.run",
        return_value=mocker.Mock(returncode=1, stderr="Error message"),
    )

    with pytest.raises(RuntimeError, match="FFmpeg command failed"):
        _run_ffmpeg(["ffmpeg", "-version"])


def test_render_video_from_images_returns_correct_result(tmp_path: Path, mocker) -> None:
    output_dir = tmp_path / "output"
    track_path = tmp_path / "track.mp3"
    track_path.write_bytes(b"fake audio")

    images = [_make_image(0, tmp_path), _make_image(1, tmp_path)]

    # Mock FFmpeg execution
    mocker.patch("src.render_images.subprocess.run", return_value=mocker.Mock(returncode=0))

    result = render_video_from_images(
        images=images,
        track_path=track_path,
        output_dir=output_dir,
        width=1920,
        height=1080,
        fps=30,
        target_duration_seconds=10,
        scene_seconds=5,
        encode_preset="veryfast",
        crf=23,
    )

    assert isinstance(result, ImageRenderResult)
    assert result.output_path == output_dir / "final.mp4"
    assert result.concat_source_path == output_dir / "images_concat.txt"
    assert result.image_count == 2
    assert result.target_duration_seconds == 10
