from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import uvicorn

from .config import AppConfig
from .logger import setup_logger
from .main import run as pipeline_run
from .tiktok_cuts import create_tiktok_cuts


class RunRequest(BaseModel):
    track: str | None = None
    allow_recent_preferred: bool = False
    tags: list[str] | None = None
    theme: str | None = None


class TikTokCutsRequest(BaseModel):
    source_video_path: str
    clips_count: int | None = None
    clip_seconds: int | None = None
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
            source_video_path = _resolve_path(payload.source_video_path, config.data_dir)
            tracks_dir = _resolve_path(payload.tracks_dir, config.assets_tracks_dir)
            output_dir = _resolve_path(payload.output_dir, config.tiktok_output_dir)

            clips_count = payload.clips_count or config.tiktok_clips_per_run
            clip_seconds = payload.clip_seconds or config.tiktok_clip_seconds

            logger.info(
                "TRIGGER: tiktok cuts requested | source=%s clips_count=%s clip_seconds=%s tracks_dir=%s output_dir=%s",
                source_video_path,
                clips_count,
                clip_seconds,
                tracks_dir,
                output_dir,
            )
            results = create_tiktok_cuts(
                source_video_path=source_video_path,
                tracks_dir=tracks_dir,
                output_dir=output_dir,
                clips_count=max(1, clips_count),
                clip_seconds=max(5, clip_seconds),
                width=config.tiktok_width,
                height=config.tiktok_height,
                fps=config.fps,
                encode_preset=config.render_preset,
                crf=config.render_crf,
            )
            return {
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
