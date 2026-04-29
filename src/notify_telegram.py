from __future__ import annotations

from pathlib import Path

import requests


def send_files_to_telegram(bot_token: str, chat_id: str, file_paths: list[Path], caption_prefix: str = "") -> None:
    if not bot_token or not chat_id or not file_paths:
        return

    api_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    for index, file_path in enumerate(file_paths, start=1):
        caption = f"{caption_prefix} clip {index}/{len(file_paths)}".strip()
        with file_path.open("rb") as file_data:
            response = requests.post(
                api_url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (file_path.name, file_data, "video/mp4")},
                timeout=120,
            )
        response.raise_for_status()
