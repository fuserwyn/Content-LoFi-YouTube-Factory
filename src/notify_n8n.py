from __future__ import annotations

import requests


def send_run_notification(webhook_url: str, payload: dict) -> None:
    if not webhook_url:
        return
    response = requests.post(webhook_url, json=payload, timeout=20)
    response.raise_for_status()
