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


def _mock_response(mocker, *, status=200, body=None, content='{"highlights": []}',
                   finish_reason="stop", refusal=None):
    if body is None:
        message = {"content": content}
        if refusal:
            message["refusal"] = refusal
        body = {"choices": [{"message": message, "finish_reason": finish_reason}]}
    resp = mocker.Mock(status_code=status, text="")
    resp.json.return_value = body
    return resp


def _patch_post(mocker, response):
    return mocker.patch("src.highlights.requests.post", return_value=response)


def test_find_highlights_returns_empty_without_segments(mocker) -> None:
    post = mocker.patch("src.highlights.requests.post")

    assert find_highlights([], HOUR_MS, "key") == []
    post.assert_not_called()


def test_find_highlights_requires_a_key(mocker) -> None:
    mocker.patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False)

    with pytest.raises(HighlightError, match="OPENROUTER_API_KEY"):
        find_highlights(_segments(), HOUR_MS, "")


def test_find_highlights_uses_configured_default(mocker) -> None:
    mocker.patch.dict("os.environ", {"OPENROUTER_MODEL": ""}, clear=False)
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key")

    assert post.call_args.kwargs["json"]["model"] == "anthropic/claude-haiku-4.5"


def test_model_can_be_swapped_by_env(mocker) -> None:
    # Сравнивать модели на своём контенте надо без передеплоя.
    mocker.patch.dict("os.environ", {"OPENROUTER_MODEL": "openai/gpt-oss-20b:free"}, clear=False)
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key")

    assert post.call_args.kwargs["json"]["model"] == "openai/gpt-oss-20b:free"


def test_explicit_model_wins_over_env(mocker) -> None:
    mocker.patch.dict("os.environ", {"OPENROUTER_MODEL": "from/env"}, clear=False)
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key", model="explicit/model")

    assert post.call_args.kwargs["json"]["model"] == "explicit/model"


def test_fallback_list_never_repeats_primary(mocker) -> None:
    # Дубль в списке — потраченная впустую повторная попытка на той же модели.
    mocker.patch.dict(
        "os.environ",
        {"OPENROUTER_MODEL": "a/b", "OPENROUTER_FALLBACK_MODELS": "a/b, c/d"},
        clear=False,
    )
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key")

    assert post.call_args.kwargs["json"]["models"] == ["a/b", "c/d"]


def test_find_highlights_requests_structured_output(mocker) -> None:
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key")

    body = post.call_args.kwargs["json"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True


def test_find_highlights_pins_routing_to_capable_endpoints(mocker) -> None:
    # Без require_parameters запрос мог бы уехать туда, где схемы нет,
    # и вместо гарантированного JSON вернулся бы свободный текст.
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key")

    assert post.call_args.kwargs["json"]["provider"]["require_parameters"] is True


def test_find_highlights_declares_fallback_models(mocker) -> None:
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "key")

    models = post.call_args.kwargs["json"]["models"]
    assert models[0] == "anthropic/claude-haiku-4.5"
    assert len(models) > 1


def test_find_highlights_sends_bearer_auth(mocker) -> None:
    post = _patch_post(mocker, _mock_response(mocker))

    find_highlights(_segments(), HOUR_MS, "secret-key")

    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-key"


def test_find_highlights_raises_on_http_error(mocker) -> None:
    _patch_post(mocker, _mock_response(mocker, status=402))

    with pytest.raises(HighlightError, match="OpenRouter 402"):
        find_highlights(_segments(), HOUR_MS, "key")


def test_find_highlights_raises_on_refusal(mocker) -> None:
    # Отказ приходит отдельным полем — читать content в этом случае незачем.
    _patch_post(mocker, _mock_response(mocker, refusal="нельзя", content=""))

    with pytest.raises(HighlightError, match="отклонила"):
        find_highlights(_segments(), HOUR_MS, "key")


def test_find_highlights_raises_on_truncated_response(mocker) -> None:
    _patch_post(mocker, _mock_response(mocker, content='{"high', finish_reason="length"))

    with pytest.raises(HighlightError, match="обрезан"):
        find_highlights(_segments(), HOUR_MS, "key")


def test_find_highlights_raises_on_invalid_json(mocker) -> None:
    _patch_post(mocker, _mock_response(mocker, content="не json"))

    with pytest.raises(HighlightError, match="невалидный JSON"):
        find_highlights(_segments(), HOUR_MS, "key")


def test_find_highlights_raises_when_no_choices(mocker) -> None:
    _patch_post(mocker, _mock_response(mocker, body={"choices": []}))

    with pytest.raises(HighlightError, match="ни одного варианта"):
        find_highlights(_segments(), HOUR_MS, "key")


def test_find_highlights_caps_result_count(mocker) -> None:
    import json as _json

    # Транскрипт должен покрывать окна: иначе подтяжка границ схлопнет их.
    long_transcript = [
        TranscriptSegment(i * 70_000, i * 70_000 + 30_000, f"реплика {i}")
        for i in range(8)
    ]
    windows = [(i * 70_000, i * 70_000 + 30_000, 0.9 - i / 100) for i in range(8)]
    _patch_post(mocker, _mock_response(mocker, content=_json.dumps(_payload(*windows))))

    found = find_highlights(long_transcript, HOUR_MS, "key", max_count=3)

    assert len(found) == 3


def _speech() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(0, 10_000, "первая"),
        TranscriptSegment(10_000, 40_000, "вторая"),
        TranscriptSegment(40_000, 75_000, "третья"),
    ]


def test_snap_pulls_boundaries_onto_speech_edges() -> None:
    from src.highlights import snap_to_speech

    # Модель отдала окно, начинающееся и кончающееся посреди реплик.
    rough = Highlight(15_000, 50_000, 0.9, "t", "r")

    snapped = snap_to_speech(rough, _speech(), 20_000, 80_000)

    assert snapped.start_ms == 10_000   # назад, к началу второй реплики
    assert snapped.end_ms == 75_000     # вперёд, чтобы третья договорилась


def test_snap_keeps_already_aligned_window() -> None:
    from src.highlights import snap_to_speech

    exact = Highlight(10_000, 40_000, 0.9, "t", "r")

    assert snap_to_speech(exact, _speech(), 20_000, 60_000) == exact


def test_snap_drops_window_that_grows_past_the_limit() -> None:
    from src.highlights import snap_to_speech

    rough = Highlight(15_000, 50_000, 0.9, "t", "r")

    # После подтяжки окно станет 65 секунд — длиннее допустимого.
    assert snap_to_speech(rough, _speech(), 20_000, 60_000) is None


def test_snap_is_noop_without_transcript() -> None:
    from src.highlights import snap_to_speech

    rough = Highlight(15_000, 50_000, 0.9, "t", "r")

    assert snap_to_speech(rough, [], 20_000, 60_000) == rough


def test_find_highlights_returns_windows_aligned_to_speech(mocker) -> None:
    import json as _json

    _patch_post(mocker, _mock_response(
        mocker, content=_json.dumps(_payload((15_000, 35_000, 0.9)))
    ))

    found = find_highlights(_speech(), 75_000, "key", min_seconds=20, max_seconds=60)

    assert found[0].start_ms == 10_000
    assert found[0].end_ms == 40_000
