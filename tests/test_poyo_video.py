"""Tests for Poyo API helpers."""

from pathlib import Path

import pytest

from src.poyo_video import _get_nested, generate_stitched_poyo_videos


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


def test_generate_stitched_invokes_generation_per_segment_and_concat(tmp_path: Path, mocker) -> None:
    out = tmp_path / "stitched.mp4"

    def _fake_download(**kwargs: object) -> dict:
        p = kwargs["output_path"]
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_bytes(b"x")
        return {"job_id": "task-x", "output_path": str(p)}

    mock_one = mocker.patch("src.poyo_video.generate_and_download_poyo_video", side_effect=_fake_download)
    mock_concat = mocker.patch("src.poyo_video.concat_mp4_files_ffmpeg")

    base = {"model": "seedance-2-fast", "input": {"prompt": "a", "duration": 15}}
    generate_stitched_poyo_videos(
        api_key="k",
        base_url="https://api.poyo.ai",
        generate_path="/api/generate/submit",
        status_path_template="/api/generate/status/{job_id}",
        base_payload=base,
        segment_count=2,
        output_path=out,
        id_field="id",
    )

    assert mock_one.call_count == 2
    seeds = [mock_one.call_args_list[i][1]["payload"]["input"]["seed"] for i in range(2)]
    assert seeds == [10000, 10001]
    mock_concat.assert_called_once()
    call_args = mock_concat.call_args[0]
    assert len(call_args[0]) == 2
    assert call_args[1] == out
