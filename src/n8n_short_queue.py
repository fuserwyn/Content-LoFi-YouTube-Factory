"""Persist Shorts publish queue on disk so n8n does not rely only on workflow staticData."""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_QUEUE_FILE = "n8n_short_publish_queue.json"
_LOCK_FILE = "n8n_short_publish_queue.lock"
_STALE_IN_FLIGHT_MS = 45 * 60 * 1000


def _queue_path(data_dir: Path) -> Path:
    return data_dir / _QUEUE_FILE


def _now_ms() -> int:
    return int(time.time() * 1000)


@contextmanager
def _file_lock(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / _LOCK_FILE
    with open(lock_path, "w", encoding="utf-8") as fp:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _build_publish_body(main_meta: dict[str, Any], short: dict[str, Any]) -> dict[str, Any]:
    tags = main_meta.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "short_path": short["path"],
        "main_title": str(main_meta.get("title") or "Short")[:500],
        "description": str(main_meta.get("description") or ""),
        "tags": list(tags),
        "short_index": int(short.get("index", 0)),
        "shorts_privacy_status": "public",
        "cleanup_after": True,
    }


def persist_queue_after_render(data_dir: Path, workflow_result: dict[str, Any], gap_ms: int) -> None:
    """Called after successful /workflow/render-main-and-shorts (inner workflow dict)."""
    shorts_files = workflow_result.get("shorts_files") or []
    main_meta = workflow_result.get("main_meta") or {"title": "", "description": "", "tags": []}
    now = _now_ms()
    gap = max(0, gap_ms)
    shorts: list[dict[str, Any]] = []
    for i, s in enumerate(shorts_files):
        if isinstance(s, dict) and s.get("path"):
            shorts.append({"path": str(s["path"]), "index": int(s.get("index", i))})
    state = {
        "version": 1,
        "main_meta": {
            "title": main_meta.get("title") or "",
            "description": main_meta.get("description") or "",
            "tags": list(main_meta.get("tags") or [])
            if isinstance(main_meta.get("tags"), list)
            else [],
        },
        "shorts": shorts,
        "next_publish_after_ms": now + gap if shorts else None,
        "in_flight": None,
    }
    with _file_lock(data_dir):
        _atomic_write(_queue_path(data_dir), json.dumps(state, ensure_ascii=False))


def peek_next_job(data_dir: Path, gap_ms: int) -> dict[str, Any]:
    """Always JSON 200: { ready, reason?, publishBody?, wait_ms? }."""
    gap = max(0, gap_ms)
    with _file_lock(data_dir):
        path = _queue_path(data_dir)
        if not path.is_file():
            return {"ready": False, "reason": "no_queue"}
        state = json.loads(path.read_text(encoding="utf-8"))
        shorts: list[dict[str, Any]] = list(state.get("shorts") or [])
        now = _now_ms()
        inflight = state.get("in_flight")

        if inflight and isinstance(inflight, dict):
            started = int(inflight.get("started_ms", 0))
            if now - started < _STALE_IN_FLIGHT_MS:
                meta = state.get("main_meta") or {}
                fake_short = {
                    "path": inflight.get("path", ""),
                    "index": int(inflight.get("index", 0)),
                }
                pb = _build_publish_body(meta, fake_short)
                return {"ready": True, "publishBody": pb, "resume_in_flight": True}
            state["in_flight"] = None

        if not shorts:
            _atomic_write(path, json.dumps(state, ensure_ascii=False))
            return {"ready": False, "reason": "queue_empty"}

        next_after = state.get("next_publish_after_ms")
        if next_after is not None and now < int(next_after):
            return {
                "ready": False,
                "reason": "before_deadline",
                "wait_ms": int(next_after) - now,
            }

        head = shorts[0]
        state["in_flight"] = {
            "path": head["path"],
            "index": int(head.get("index", 0)),
            "started_ms": now,
        }
        _atomic_write(path, json.dumps(state, ensure_ascii=False))
        meta = state.get("main_meta") or {}
        return {"ready": True, "publishBody": _build_publish_body(meta, head)}


def ack_publish(data_dir: Path, gap_ms: int) -> dict[str, Any]:
    gap = max(0, gap_ms)
    with _file_lock(data_dir):
        path = _queue_path(data_dir)
        if not path.is_file():
            return {"ok": False, "remaining": 0, "all_shorts_done": True}
        state = json.loads(path.read_text(encoding="utf-8"))
        shorts: list[dict[str, Any]] = list(state.get("shorts") or [])
        inflight = state.get("in_flight")
        if not inflight or not shorts:
            state["in_flight"] = None
            _atomic_write(path, json.dumps(state, ensure_ascii=False))
            return {"ok": False, "remaining": len(shorts), "all_shorts_done": len(shorts) == 0}

        head = shorts[0]
        if str(head.get("path")) != str(inflight.get("path")) or int(head.get("index", 0)) != int(
            inflight.get("index", 0)
        ):
            state["in_flight"] = None
            _atomic_write(path, json.dumps(state, ensure_ascii=False))
            return {"ok": False, "remaining": len(shorts), "all_shorts_done": False}

        shorts.pop(0)
        state["shorts"] = shorts
        state["in_flight"] = None
        now = _now_ms()
        if shorts:
            state["next_publish_after_ms"] = now + gap
        else:
            state["next_publish_after_ms"] = None
        _atomic_write(path, json.dumps(state, ensure_ascii=False))
        remaining = len(shorts)
        return {"ok": True, "remaining": remaining, "all_shorts_done": remaining == 0}
