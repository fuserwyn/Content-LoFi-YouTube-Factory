from pathlib import Path

import pytest

from src.shorts_cut import ShortsCutError, _build_filter, cut_short


def _fake_ok(mocker):
    return mocker.patch(
        "src.shorts_cut.subprocess.run",
        return_value=mocker.Mock(returncode=0, stderr=""),
    )


def test_cut_short_raises_on_missing_source(tmp_path: Path) -> None:
    with pytest.raises(ShortsCutError, match="Source video not found"):
        cut_short(
            source_path=tmp_path / "missing.mp4",
            output_path=tmp_path / "out.mp4",
            start_ms=0,
            end_ms=1000,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )


def test_cut_short_raises_on_empty_window(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x")

    with pytest.raises(ShortsCutError, match="Empty window"):
        cut_short(
            source_path=source,
            output_path=tmp_path / "out.mp4",
            start_ms=2000,
            end_ms=2000,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )


def test_cut_short_keeps_source_audio(tmp_path: Path, mocker) -> None:
    # Ключевое отличие от tiktok_cuts: звук берётся из исходника (0:a),
    # а не подменяется музыкальным треком (1:a).
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x")
    run = _fake_ok(mocker)

    cut_short(
        source_path=source,
        output_path=tmp_path / "out.mp4",
        start_ms=1000,
        end_ms=5000,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    cmd = run.call_args[0][0]
    assert "0:a:0?" in cmd
    assert "1:a:0" not in cmd


def test_cut_short_passes_window_to_ffmpeg(tmp_path: Path, mocker) -> None:
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x")
    run = _fake_ok(mocker)

    cut_short(
        source_path=source,
        output_path=tmp_path / "out.mp4",
        start_ms=2500,
        end_ms=9500,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    cmd = run.call_args[0][0]
    assert "2.500" in cmd
    assert "7.000" in cmd


def test_cut_short_writes_and_removes_ass_file(tmp_path: Path, mocker) -> None:
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x")
    run = _fake_ok(mocker)

    clip = cut_short(
        source_path=source,
        output_path=tmp_path / "out.mp4",
        start_ms=0,
        end_ms=3000,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
        ass_text="[Script Info]\n",
    )

    assert clip.has_subtitles is True
    assert "ass=out.ass" in " ".join(run.call_args[0][0])
    # Временный ASS не должен оставаться рядом с готовым клипом.
    assert not (tmp_path / "out.ass").exists()


def test_cut_short_without_subtitles_omits_ass_filter(tmp_path: Path, mocker) -> None:
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x")
    run = _fake_ok(mocker)

    clip = cut_short(
        source_path=source,
        output_path=tmp_path / "out.mp4",
        start_ms=0,
        end_ms=3000,
        width=1080,
        height=1920,
        fps=30,
        encode_preset="veryfast",
        crf=23,
    )

    assert clip.has_subtitles is False
    assert "ass=" not in " ".join(run.call_args[0][0])


def test_cut_short_raises_on_ffmpeg_failure(tmp_path: Path, mocker) -> None:
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x")
    mocker.patch(
        "src.shorts_cut.subprocess.run",
        return_value=mocker.Mock(returncode=1, stderr="boom"),
    )

    with pytest.raises(ShortsCutError, match="FFmpeg shorts render failed"):
        cut_short(
            source_path=source,
            output_path=tmp_path / "out.mp4",
            start_ms=0,
            end_ms=1000,
            width=1080,
            height=1920,
            fps=30,
            encode_preset="veryfast",
            crf=23,
        )


def test_build_filter_puts_subtitles_after_crop() -> None:
    # Прожиг до crop отрендерил бы подпись в исходном разрешении и обрезал её.
    chain = _build_filter(1080, 1920, 30, "s.ass")

    assert chain.index("crop=") < chain.index("ass=")


def test_build_filter_crops_to_target_aspect() -> None:
    chain = _build_filter(1080, 1920, 30, "")

    assert "scale=1080:1920:force_original_aspect_ratio=increase" in chain
    assert "crop=1080:1920" in chain
    assert "ass=" not in chain


def test_filter_resets_pixel_aspect_ratio() -> None:
    # Неквадратный SAR наследуется от исходника: кадр 1080x1920 отображается
    # не как 9:16, и плеер тянет картинку — видео выглядит невертикальным.
    chain = _build_filter(1080, 1920, 30, "")

    assert "setsar=1" in chain
    assert chain.index("crop=") < chain.index("setsar=1")


def test_crop_offset_centres_faces() -> None:
    from src.face_focus import crop_offset

    # Лица в правой трети кадра шириной 3413 -> рамка 1080 едет вправо.
    assert crop_offset(3413, 1080, 0.75) == int(3413 * 0.75 - 540)


def test_crop_offset_stays_inside_the_frame() -> None:
    from src.face_focus import crop_offset

    assert crop_offset(3413, 1080, 0.0) == 0
    assert crop_offset(3413, 1080, 1.0) == 3413 - 1080


def test_crop_offset_falls_back_to_centre_without_faces() -> None:
    # Отсутствие лиц — нормальный исход, а не ошибка: в кадре может не быть людей.
    from src.face_focus import crop_offset

    assert crop_offset(3413, 1080, None) == (3413 - 1080) // 2


def test_filter_uses_the_offset_when_given() -> None:
    assert "crop=1080:1920:700:0" in _build_filter(1080, 1920, 30, "", 700)


def test_filter_centres_when_no_offset() -> None:
    assert "crop=1080:1920," in _build_filter(1080, 1920, 30, "", None) + ","
