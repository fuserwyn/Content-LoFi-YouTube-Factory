"""MiniMax API client unit tests."""

from pathlib import Path
from unittest.mock import MagicMock

from src.minimax_video import generate_and_download_minimax_video, minimax_t2v_body_from_payload


def test_minimax_body_from_nested_input() -> None:
    payload = {
        "model": "ignored-seedance",
        "input": {"prompt": "ocean lofi", "duration": 10, "resolution": "768p"},
    }
    body = minimax_t2v_body_from_payload(
        payload,
        default_model="MiniMax-Hailuo-02",
        default_duration=6,
        default_resolution="768P",
    )
    assert body["model"] == "MiniMax-Hailuo-02"
    assert body["prompt"] == "ocean lofi"
    assert body["duration"] == 10
    assert body["resolution"] == "768P"


def test_minimax_body_minimax_override_block() -> None:
    payload = {
        "input": {"prompt": "rain"},
        "minimax": {"model": "MiniMax-Hailuo-2.3", "duration": 6, "resolution": "1080P"},
    }
    body = minimax_t2v_body_from_payload(
        payload,
        default_model="MiniMax-Hailuo-02",
        default_duration=10,
        default_resolution="768P",
    )
    assert body["model"] == "MiniMax-Hailuo-2.3"
    assert body["duration"] == 6
    assert body["resolution"] == "1080P"


def test_minimax_download_end_to_end(mocker, tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"

    post_resp = MagicMock()
    post_resp.raise_for_status = MagicMock()
    post_resp.json.return_value = {"task_id": "t1", "base_resp": {"status_code": 0, "status_msg": "success"}}

    poll_working = MagicMock()
    poll_working.raise_for_status = MagicMock()
    poll_working.json.return_value = {"status": "Processing"}

    poll_done = MagicMock()
    poll_done.raise_for_status = MagicMock()
    poll_done.json.return_value = {"status": "Success", "file_id": "f99"}

    ret = MagicMock()
    ret.raise_for_status = MagicMock()
    ret.json.return_value = {"file": {"download_url": "https://cdn.example/v.mp4"}}

    dl = MagicMock()
    dl.raise_for_status = MagicMock()
    dl.content = b"mp4bytes"

    mocker.patch(
        "src.minimax_video.requests.post",
        return_value=post_resp,
    )
    mocker.patch(
        "src.minimax_video.requests.get",
        side_effect=[poll_working, poll_done, ret, dl],
    )

    result = generate_and_download_minimax_video(
        api_key="k",
        base_url="https://api.minimax.io",
        payload={"prompt": "test"},
        output_path=out,
        default_model="MiniMax-Hailuo-02",
        default_duration=10,
        default_resolution="768P",
        poll_interval_seconds=1,
        max_wait_seconds=30,
    )

    assert result["job_id"] == "t1"
    assert result["file_id"] == "f99"
    assert out.read_bytes() == b"mp4bytes"
