"""Persist Shorts publish queue on disk so n8n does not rely only on workflow staticData."""

from __future__ import annotations

import fcntl
import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_QUEUE_FILE = "n8n_short_publish_queue.json"
_LOCK_FILE = "n8n_short_publish_queue.lock"
_PUBLISH_LOCK_MS = 15 * 60 * 1000


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
        "publish_lock_ms": None,
    }
    with _file_lock(data_dir):
        _atomic_write(_queue_path(data_dir), json.dumps(state, ensure_ascii=False))
    logger.info(
        "n8n_short_queue: persisted after render | shorts=%d next_publish_after_ms=%s",
        len(shorts),
        state.get("next_publish_after_ms"),
    )
    if not shorts:
        logger.warning(
            "n8n_short_queue: no shorts in workflow_result — queue empty (check create_tiktok_cuts / shorts_count)"
        )


def _peek_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """n8n-friendly: strict If on booleans often fails; use publish_int === 1."""
    out = dict(payload)
    out["publish_int"] = 1 if out.get("ready") is True else 0
    return out


def peek_next_job(data_dir: Path, gap_ms: int) -> dict[str, Any]:
    """Read-only peek. Always JSON 200: { ready, publish_int, reason?, publishBody?, wait_ms? }.

    No in-flight mutation: n8n may retry peek until POST publish-short + ack succeed.
    """
    _ = gap_ms
    with _file_lock(data_dir):
        path = _queue_path(data_dir)
        if not path.is_file():
            logger.debug("n8n_short_queue: peek no_queue_file")
            return _peek_envelope({"ready": False, "reason": "no_queue"})
        state = json.loads(path.read_text(encoding="utf-8"))
        shorts: list[dict[str, Any]] = list(state.get("shorts") or [])
        now = _now_ms()

        if not shorts:
            return _peek_envelope({"ready": False, "reason": "queue_empty"})

        next_after = state.get("next_publish_after_ms")
        if next_after is not None and now < int(next_after):
            w = int(next_after) - now
            logger.debug("n8n_short_queue: peek before_deadline wait_ms=%s", w)
            return _peek_envelope(
                {
                    "ready": False,
                    "reason": "before_deadline",
                    "wait_ms": w,
                }
            )

        plock = state.get("publish_lock_ms")
        if plock is not None:
            age = now - int(plock)
            if age < _PUBLISH_LOCK_MS:
                w = _PUBLISH_LOCK_MS - age
                logger.debug("n8n_short_queue: peek publish_in_progress wait_ms=%s", w)
                return _peek_envelope(
                    {
                        "ready": False,
                        "reason": "publish_in_progress",
                        "wait_ms": w,
                    }
                )
            state["publish_lock_ms"] = None

        head = shorts[0]
        meta = state.get("main_meta") or {}
        state["publish_lock_ms"] = now
        _atomic_write(path, json.dumps(state, ensure_ascii=False))
        out = {"ready": True, "publishBody": _build_publish_body(meta, head)}
        logger.info(
            "n8n_short_queue: peek ready | short_index=%s path=%s",
            head.get("index"),
            head.get("path"),
        )
        return _peek_envelope(out)


def ack_publish(data_dir: Path, gap_ms: int) -> dict[str, Any]:
    """Pop front short after successful YouTube upload (call once per publish)."""
    gap = max(0, gap_ms)
    with _file_lock(data_dir):
        path = _queue_path(data_dir)
        if not path.is_file():
            return {"ok": False, "remaining": 0, "all_shorts_done": True}
        state = json.loads(path.read_text(encoding="utf-8"))
        shorts: list[dict[str, Any]] = list(state.get("shorts") or [])
        if not shorts:
            return {"ok": False, "remaining": 0, "all_shorts_done": True}

        shorts.pop(0)
        state["shorts"] = shorts
        state["publish_lock_ms"] = None
        now = _now_ms()
        if shorts:
            state["next_publish_after_ms"] = now + gap
        else:
            state["next_publish_after_ms"] = None
        _atomic_write(path, json.dumps(state, ensure_ascii=False))
        remaining = len(shorts)
        logger.info("n8n_short_queue: ack | remaining=%s all_done=%s", remaining, remaining == 0)
        return {"ok": True, "remaining": remaining, "all_shorts_done": remaining == 0}
