"""Tests for Poyo API helpers."""

from src.poyo_video import _get_nested


def test_get_nested_dict_only() -> None:
    assert _get_nested({"a": {"b": "x"}}, "a.b") == "x"


def test_get_nested_list_index() -> None:
    payload = {
        "code": 200,
        "data": {
            "status": "finished",
            "files": [{"file_url": "https://cdn.example/v.mp4", "file_type": "video"}],
        },
    }
    assert _get_nested(payload, "data.status") == "finished"
    assert _get_nested(payload, "data.files.0.file_url") == "https://cdn.example/v.mp4"
