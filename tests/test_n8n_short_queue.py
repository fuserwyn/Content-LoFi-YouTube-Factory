"""n8n disk queue for Shorts after main render."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.n8n_short_queue import ack_publish, peek_next_job, persist_queue_after_render


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def test_persist_peek_ack_flow(data_dir: Path) -> None:
    gap = 60_000
    wf = {
        "main_meta": {"title": "T", "description": "D", "tags": ["a"]},
        "shorts_files": [
            {"path": "/tmp/s0.mp4", "index": 0},
            {"path": "/tmp/s1.mp4", "index": 1},
        ],
    }
    persist_queue_after_render(data_dir, wf, gap)
    t0 = int(time.time() * 1000)
    r0 = peek_next_job(data_dir, gap)
    assert r0["ready"] is False
    assert r0["publish_int"] == 0
    assert r0["reason"] == "before_deadline"

    path = data_dir / "n8n_short_publish_queue.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["next_publish_after_ms"] = t0 - 1
    path.write_text(json.dumps(state), encoding="utf-8")

    r1 = peek_next_job(data_dir, gap)
    assert r1["ready"] is True
    assert r1["publish_int"] == 1
    assert r1["publishBody"]["short_path"] == "/tmp/s0.mp4"

    r1b = peek_next_job(data_dir, gap)
    assert r1b["reason"] == "publish_in_progress"

    a1 = ack_publish(data_dir, gap)
    assert a1["ok"] is True
    assert a1["remaining"] == 1

    state = json.loads(path.read_text(encoding="utf-8"))
    assert int(state["next_publish_after_ms"]) > t0

    state["next_publish_after_ms"] = 0
    path.write_text(json.dumps(state), encoding="utf-8")

    r2 = peek_next_job(data_dir, gap)
    assert r2["ready"] is True
    assert r2["publishBody"]["short_index"] == 1

    a2 = ack_publish(data_dir, gap)
    assert a2["ok"] is True
    assert a2["remaining"] == 0
    assert a2["all_shorts_done"] is True
