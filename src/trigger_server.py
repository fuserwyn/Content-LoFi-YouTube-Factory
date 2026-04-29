from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import uvicorn

from .config import AppConfig
from .logger import setup_logger
from .main import run as pipeline_run
from .notify_telegram import send_files_to_telegram
from .tiktok_cuts import TikTokClipResult, create_tiktok_cuts


class RunRequest(BaseModel):
    track: str | None = None
    allow_recent_preferred: bool = False
    tags: list[str] | None = None
    theme: str | None = None


class TikTokCutsRequest(BaseModel):
    source_video_path: str
    clips_count: int | None = None
    clip_seconds: int | None = None
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    tracks_dir: str | None = None
    output_dir: str | None = None


def start_trigger_server(config: AppConfig) -> None:
    logger = setup_logger()
    app = FastAPI()
    run_lock = threading.Lock()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "mode": "webhook"}

    @app.post("/run")
    def run_now(payload: RunRequest, x_trigger_key: str | None = Header(default=None)) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            logger.info(
                "TRIGGER: manual run requested via webhook | track=%s allow_recent=%s tags=%s theme=%s",
                payload.track,
                payload.allow_recent_preferred,
                payload.tags,
                payload.theme,
            )
            pipeline_run(
                preferred_track=payload.track,
                allow_recent_preferred=payload.allow_recent_preferred,
                content_tags_override=payload.tags,
            )
            return {"status": "ok", "message": "run completed"}
        finally:
            run_lock.release()

    @app.post("/tiktok-cuts")
    def tiktok_cuts(payload: TikTokCutsRequest, x_trigger_key: str | None = Header(default=None)) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            source_video_path = _resolve_source_video_path(payload.source_video_path, config)
            tracks_dir = _resolve_tracks_dir(payload.tracks_dir, config)
            output_dir = _resolve_path(payload.output_dir, config.tiktok_output_dir)

            clips_count = config.tiktok_clips_per_run if payload.clips_count is None else payload.clips_count
            clip_seconds = config.tiktok_clip_seconds if payload.clip_seconds is None else payload.clip_seconds
            clip_min_seconds = payload.clip_min_seconds
            clip_max_seconds = payload.clip_max_seconds

            logger.info(
                "TRIGGER: tiktok cuts requested | source=%s clips_count=%s clip_seconds=%s tracks_dir=%s output_dir=%s",
                source_video_path,
                clips_count,
                clip_seconds,
                tracks_dir,
                output_dir,
            )
            def _on_clip_ready(item: TikTokClipResult) -> None:
                if not config.telegram_send_tiktok:
                    return
                send_files_to_telegram(
                    bot_token=config.telegram_bot_token,
                    chat_id=config.telegram_chat_id,
                    file_paths=[item.output_path],
                    caption_prefix="TikTok cut ready",
                )

            results = create_tiktok_cuts(
                source_video_path=source_video_path,
                tracks_dir=tracks_dir,
                output_dir=output_dir,
                clips_count=clips_count,
                clip_seconds=max(5, clip_seconds),
                width=config.tiktok_width,
                height=config.tiktok_height,
                fps=config.fps,
                encode_preset=config.render_preset,
                crf=config.render_crf,
                clip_min_seconds=max(5, clip_min_seconds) if clip_min_seconds is not None else None,
                clip_max_seconds=max(5, clip_max_seconds) if clip_max_seconds is not None else None,
                on_clip_ready=_on_clip_ready,
            )
            response_payload = {
                "status": "ok",
                "message": "tiktok cuts completed",
                "clips_count": len(results),
                "clips": [
                    {
                        "path": str(item.output_path),
                        "track_path": str(item.track_path),
                        "start_second": item.start_second,
                        "duration_second": item.duration_second,
                    }
                    for item in results
                ],
            }
            if config.telegram_send_tiktok:
                response_payload["telegram_sent"] = True
            return response_payload
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: tiktok cuts failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            run_lock.release()

    logger.info("TRIGGER: server started on 0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


def _resolve_path(raw: str | None, default_path: Path) -> Path:
    fallback = Path(default_path)
    if raw is None or not raw.strip():
        return fallback
    candidate = Path(raw.strip())
    if candidate.is_absolute():
        return candidate
    return (fallback / candidate).resolve()


def _resolve_source_video_path(raw: str, config: AppConfig) -> Path:
    requested = Path(raw.strip())
    search_dirs = [
        config.assets_source_videos_dir,
        Path("/assets/source_videos"),
        Path("/storage/videos"),
        config.data_dir / "videos",
    ]

    # 1) If absolute and exists, use as-is.
    if requested.is_absolute() and requested.exists():
        return requested

    # 2) Try exact relative path under known directories.
    if not requested.is_absolute():
        for base in search_dirs:
            candidate = (base / requested).resolve()
            if candidate.exists():
                return candidate

    # 3) Try by filename only across known directories.
    filename = requested.name
    for base in search_dirs:
        candidate = (base / filename).resolve()
        if candidate.exists():
            return candidate

    # Keep the original path in error for clear debugging.
    return requested


def _resolve_tracks_dir(raw: str | None, config: AppConfig) -> Path:
    if raw and raw.strip():
        return _resolve_path(raw, config.assets_tracks_dir)

    candidates = [
        config.assets_tracks_dir,
        Path("/assets/tracks"),
        Path("/storage/tracks"),
    ]
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return config.assets_tracks_dir
