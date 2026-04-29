from __future__ import annotations

import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import uvicorn

from .config import AppConfig
from .logger import setup_logger
from .main import run as pipeline_run


class RunRequest(BaseModel):
    track: str | None = None
    allow_recent_preferred: bool = False


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
                "TRIGGER: manual run requested via webhook | track=%s allow_recent=%s",
                payload.track,
                payload.allow_recent_preferred,
            )
            pipeline_run(
                preferred_track=payload.track,
                allow_recent_preferred=payload.allow_recent_preferred,
            )
            return {"status": "ok", "message": "run completed"}
        finally:
            run_lock.release()

    logger.info("TRIGGER: server started on 0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
