from __future__ import annotations

import threading

from flask import Flask, jsonify, request

from .config import AppConfig
from .logger import setup_logger
from .main import run as pipeline_run


def start_trigger_server(config: AppConfig) -> None:
    logger = setup_logger()
    app = Flask(__name__)
    run_lock = threading.Lock()

    @app.get("/health")
    def health() -> tuple[dict, int]:
        return {"status": "ok", "mode": "webhook"}, 200

    @app.post("/run")
    def run_now() -> tuple[dict, int]:
        provided_key = request.headers.get("X-Trigger-Key", "")
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            return {"status": "error", "message": "unauthorized"}, 401

        if not run_lock.acquire(blocking=False):
            return {"status": "busy", "message": "run already in progress"}, 409

        try:
            logger.info("TRIGGER: manual run requested via webhook")
            pipeline_run()
            return {"status": "ok", "message": "run completed"}, 200
        finally:
            run_lock.release()

    logger.info("TRIGGER: server started on 0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080)
