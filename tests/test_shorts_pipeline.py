from pathlib import Path

from src.highlights import Highlight
from src.shorts_cut import ShortClip
from src.shorts_pipeline import build_shorts
from src.transcribe import TranscriptSegment, Word


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            0, 30_000, "первый кусок",
            [Word(i * 1000, i * 1000 + 800, f"w{i}") for i in range(30)],
        ),
        TranscriptSegment(
            30_000, 60_000, "второй кусок",
            [Word(30_000 + i * 1000, 30_000 + i * 1000 + 800, f"x{i}") for i in range(30)],
        ),
    ]


def _wire(mocker, *, segments=None, highlights=None, speech=True):
    """Подменяет все внешние вызовы: Whisper, Claude и ffmpeg."""
    mocker.patch("src.shorts_pipeline.probe_duration_seconds", return_value=600.0)
    mocker.patch(
        "src.shorts_pipeline.transcribe",
        return_value=_segments() if segments is None else segments,
    )
    mocker.patch("src.shorts_pipeline.has_speech", return_value=speech)
    find = mocker.patch(
        "src.shorts_pipeline.find_highlights",
        return_value=[] if highlights is None else highlights,
    )
    cut = mocker.patch(
        "src.shorts_pipeline.cut_short",
        side_effect=lambda **kw: ShortClip(
            path=kw["output_path"],
            start_ms=kw["start_ms"],
            end_ms=kw["end_ms"],
            has_subtitles=bool(kw.get("ass_text")),
        ),
    )
    return find, cut


def test_build_shorts_stops_when_source_has_no_speech(tmp_path: Path, mocker) -> None:
    # Немое видео: отбирать хайлайты не по чему — Claude звать не за что.
    find, cut = _wire(mocker, speech=False)

    result = build_shorts(tmp_path / "src.mp4", tmp_path / "out")

    assert result.had_speech is False
    assert result.clips == []
    find.assert_not_called()
    cut.assert_not_called()


def test_build_shorts_cuts_one_clip_per_highlight(tmp_path: Path, mocker) -> None:
    highlights = [
        Highlight(0, 25_000, 0.9, "a", "r"),
        Highlight(30_000, 55_000, 0.7, "b", "r"),
    ]
    _, cut = _wire(mocker, highlights=highlights)

    result = build_shorts(tmp_path / "src.mp4", tmp_path / "out")

    assert len(result.clips) == 2
    assert cut.call_count == 2


def test_build_shorts_passes_source_duration_to_highlights(tmp_path: Path, mocker) -> None:
    find, _ = _wire(mocker)

    build_shorts(tmp_path / "src.mp4", tmp_path / "out")

    assert find.call_args[0][1] == 600_000


def test_build_shorts_burns_subtitles_for_the_clip_window(tmp_path: Path, mocker) -> None:
    _, cut = _wire(mocker, highlights=[Highlight(0, 25_000, 0.9, "a", "r")])

    build_shorts(tmp_path / "src.mp4", tmp_path / "out")

    ass_text = cut.call_args.kwargs["ass_text"]
    assert "[Script Info]" in ass_text
    assert "Dialogue:" in ass_text


def test_build_shorts_can_skip_subtitles(tmp_path: Path, mocker) -> None:
    _, cut = _wire(mocker, highlights=[Highlight(0, 25_000, 0.9, "a", "r")])

    build_shorts(
        tmp_path / "src.mp4", tmp_path / "out", burn_subtitles=False
    )

    assert cut.call_args.kwargs["ass_text"] == ""


def test_build_shorts_omits_subtitles_when_window_has_no_words(
    tmp_path: Path, mocker
) -> None:
    # Хайлайт за пределами речи — прожигать нечего, но клип всё равно режем.
    _, cut = _wire(mocker, highlights=[Highlight(500_000, 525_000, 0.9, "a", "r")])

    build_shorts(tmp_path / "src.mp4", tmp_path / "out")

    assert cut.call_args.kwargs["ass_text"] == ""


def test_build_shorts_reports_each_clip_as_it_lands(tmp_path: Path, mocker) -> None:
    # Бот отдаёт первый шортс, не дожидаясь остальных.
    highlights = [
        Highlight(0, 25_000, 0.9, "a", "r"),
        Highlight(30_000, 55_000, 0.7, "b", "r"),
    ]
    _wire(mocker, highlights=highlights)
    seen: list[ShortClip] = []

    build_shorts(
        tmp_path / "src.mp4", tmp_path / "out", on_clip_ready=seen.append
    )

    assert len(seen) == 2


def test_build_shorts_transcribes_once_for_both_uses(tmp_path: Path, mocker) -> None:
    # Транскрипт нужен и для отбора, и для субтитров — но платим за него один раз.
    mocker.patch("src.shorts_pipeline.probe_duration_seconds", return_value=600.0)
    mocker.patch("src.shorts_pipeline.has_speech", return_value=True)
    mocker.patch(
        "src.shorts_pipeline.find_highlights",
        return_value=[Highlight(0, 25_000, 0.9, "a", "r")],
    )
    mocker.patch("src.shorts_pipeline.cut_short", return_value=mocker.Mock())
    transcribe = mocker.patch(
        "src.shorts_pipeline.transcribe", return_value=_segments()
    )

    build_shorts(tmp_path / "src.mp4", tmp_path / "out")

    transcribe.assert_called_once()


def test_build_shorts_names_clips_in_order(tmp_path: Path, mocker) -> None:
    highlights = [
        Highlight(0, 25_000, 0.9, "a", "r"),
        Highlight(30_000, 55_000, 0.7, "b", "r"),
    ]
    _, cut = _wire(mocker, highlights=highlights)

    build_shorts(tmp_path / "podcast.mp4", tmp_path / "out")

    names = [c.kwargs["output_path"].name for c in cut.call_args_list]
    assert names == ["podcast_short_01.mp4", "podcast_short_02.mp4"]
