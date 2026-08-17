import pytest

from src.highlights import (
    Highlight,
    HighlightError,
    _drop_overlaps,
    _parse,
    find_highlights,
    render_transcript,
)
from src.transcribe import TranscriptSegment, Word

HOUR_MS = 3_600_000


def _payload(*windows: tuple[int, int, float]) -> dict:
    return {
        "highlights": [
            {
                "start_ms": start,
                "end_ms": end,
                "score": score,
                "title": "t",
                "reason": "r",
            }
            for start, end, score in windows
        ]
    }


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(0, 4000, "первая реплика", [Word(0, 900, "первая")]),
        TranscriptSegment(4000, 9000, "вторая реплика", [Word(4000, 4900, "вторая")]),
    ]


def test_render_transcript_carries_timestamps() -> None:
    rendered = render_transcript(_segments())

    assert "[0-4000] первая реплика" in rendered
    assert "[4000-9000] вторая реплика" in rendered


def test_render_transcript_empty_is_blank() -> None:
    assert render_transcript([]) == ""


def test_drop_overlaps_keeps_higher_score() -> None:
    weak = Highlight(0, 30_000, 0.4, "", "")
    strong = Highlight(10_000, 40_000, 0.9, "", "")

    kept = _drop_overlaps([weak, strong])

    assert kept == [strong]


def test_drop_overlaps_keeps_adjacent_windows() -> None:
    # Стык встык пересечением не считается — оба клипа валидны.
    first = Highlight(0, 30_000, 0.5, "", "")
    second = Highlight(30_000, 60_000, 0.4, "", "")

    assert len(_drop_overlaps([first, second])) == 2


def test_parse_rejects_too_short_and_too_long() -> None:
    payload = _payload(
        (0, 5_000, 0.9),        # короче минимума
        (10_000, 40_000, 0.8),  # в диапазоне
        (60_000, 200_000, 0.7), # длиннее максимума
    )

    found = _parse(payload, HOUR_MS, min_ms=20_000, max_ms=60_000)

    assert len(found) == 1
    assert found[0].start_ms == 10_000


def test_parse_clamps_window_to_source_duration() -> None:
    payload = _payload((0, 90_000, 0.9))

    found = _parse(payload, source_duration_ms=45_000, min_ms=20_000, max_ms=60_000)

    assert found[0].end_ms == 45_000


def test_parse_clamps_score_to_unit_range() -> None:
    # Схема structured outputs не умеет minimum/maximum — подрезаем в коде.
    payload = _payload((0, 30_000, 7.5), (40_000, 70_000, -3.0))

    found = _parse(payload, HOUR_MS, min_ms=20_000, max_ms=60_000)

    assert {h.score for h in found} == {0.0, 1.0}


def test_parse_skips_malformed_entries() -> None:
    payload = {"highlights": [{"start_ms": "nope", "end_ms": 30_000, "score": 0.5}]}

    assert _parse(payload, HOUR_MS, min_ms=20_000, max_ms=60_000) == []


def test_parse_handles_missing_key() -> None:
    assert _parse({}, HOUR_MS, min_ms=20_000, max_ms=60_000) == []


def _mock_response(mocker, *, stop_reason="end_turn", text="{}"):
    block = mocker.Mock(type="text")
    block.text = text
    return mocker.Mock(stop_reason=stop_reason, content=[block])


def _patch_client(mocker, response):
    client = mocker.Mock()
    client.beta.messages.create.return_value = response
    mocker.patch("src.highlights.anthropic.Anthropic", return_value=client)
    return client


def test_find_highlights_returns_empty_without_segments(mocker) -> None:
    create = mocker.patch("src.highlights.anthropic.Anthropic")

    assert find_highlights([], HOUR_MS) == []
    create.assert_not_called()


def test_find_highlights_uses_opus_5(mocker) -> None:
    client = _patch_client(mocker, _mock_response(mocker, text='{"highlights": []}'))

    find_highlights(_segments(), HOUR_MS)

    assert client.beta.messages.create.call_args.kwargs["model"] == "claude-opus-5"


def test_find_highlights_requests_structured_output(mocker) -> None:
    client = _patch_client(mocker, _mock_response(mocker, text='{"highlights": []}'))

    find_highlights(_segments(), HOUR_MS)

    output_config = client.beta.messages.create.call_args.kwargs["output_config"]
    assert output_config["format"]["type"] == "json_schema"


def test_find_highlights_declares_server_side_fallback(mocker) -> None:
    # Резерв: отказ классификатора должен переигрываться на другой модели
    # сервером, а не ронять конвейер.
    client = _patch_client(mocker, _mock_response(mocker, text='{"highlights": []}'))

    find_highlights(_segments(), HOUR_MS)

    kwargs = client.beta.messages.create.call_args.kwargs
    assert kwargs["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in kwargs["betas"]


def test_find_highlights_raises_when_whole_chain_refuses(mocker) -> None:
    # Сюда попадаем, только если отказал и резерв: content пустой,
    # читать его по индексу нельзя.
    _patch_client(mocker, _mock_response(mocker, stop_reason="refusal", text=""))

    with pytest.raises(HighlightError, match="резервной"):
        find_highlights(_segments(), HOUR_MS)


def test_find_highlights_raises_on_truncated_response(mocker) -> None:
    _patch_client(mocker, _mock_response(mocker, stop_reason="max_tokens", text='{"high'))

    with pytest.raises(HighlightError, match="обрезан"):
        find_highlights(_segments(), HOUR_MS)


def test_find_highlights_raises_on_invalid_json(mocker) -> None:
    _patch_client(mocker, _mock_response(mocker, text="не json"))

    with pytest.raises(HighlightError, match="невалидный JSON"):
        find_highlights(_segments(), HOUR_MS)


def test_find_highlights_caps_result_count(mocker) -> None:
    windows = [(i * 70_000, i * 70_000 + 30_000, 0.9 - i / 100) for i in range(8)]
    import json

    _patch_client(mocker, _mock_response(mocker, text=json.dumps(_payload(*windows))))

    found = find_highlights(_segments(), HOUR_MS, max_count=3)

    assert len(found) == 3
