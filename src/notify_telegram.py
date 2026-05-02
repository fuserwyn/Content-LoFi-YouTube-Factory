from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import requests

LOGGER = logging.getLogger("content_factory")

# Bot API hard limit for sendDocument / sending files (~50 MiB). Stay slightly under for proxies.
TELEGRAM_SEND_DOCUMENT_MAX_BYTES = 49 * 1024 * 1024


def _send_files_via_mtproto(
    api_id: int,
    api_hash: str,
    session_string: str,
    chat_id: str,
    file_paths: list[Path],
    caption_prefix: str,
) -> None:
    try:
        from telethon import TelegramClient  # type: ignore[import-untyped]
        from telethon.sessions import StringSession  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("telethon is required for TELEGRAM_API_ID/API_HASH uploads") from exc

    async def _upload_all() -> None:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            for index, file_path in enumerate(file_paths, start=1):
                caption = f"{caption_prefix} clip {index}/{len(file_paths)}".strip()
                await client.send_file(int(chat_id), file_path, caption=caption or None)

    asyncio.run(_upload_all())


def send_files_to_telegram(
    bot_token: str,
    chat_id: str,
    file_paths: list[Path],
    caption_prefix: str = "",
    *,
    telegram_api_id: int = 0,
    telegram_api_hash: str = "",
    telegram_session_string: str = "",
) -> None:
    if not chat_id or not file_paths:
        return

    use_mtproto = bool(
        telegram_api_id and telegram_api_hash.strip() and telegram_session_string.strip()
    )
    if use_mtproto:
        try:
            _send_files_via_mtproto(
                telegram_api_id,
                telegram_api_hash,
                telegram_session_string,
                chat_id,
                file_paths,
                caption_prefix,
            )
            return
        except Exception as exc:
            LOGGER.warning("Telegram MTProto upload failed (%s); falling back to Bot API", exc)

    if not bot_token:
        return

    api_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    for index, file_path in enumerate(file_paths, start=1):
        caption = f"{caption_prefix} clip {index}/{len(file_paths)}".strip()
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            LOGGER.warning("Telegram: cannot read %s: %s", file_path, exc)
            continue

        if size > TELEGRAM_SEND_DOCUMENT_MAX_BYTES:
            LOGGER.warning(
                "Telegram: skip %s (%.1f MiB): over Bot API sendDocument limit (~50 MiB)",
                file_path.name,
                size / (1024 * 1024),
            )
            send_message_to_telegram(
                bot_token,
                chat_id,
                _oversize_notice(caption, file_path.name, size),
            )
            continue

        with file_path.open("rb") as file_data:
            response = requests.post(
                api_url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (file_path.name, file_data, "video/mp4")},
                timeout=120,
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            resp = exc.response
            if resp is not None and resp.status_code == 413:
                LOGGER.warning(
                    "Telegram: 413 for %s (%.1f MiB); sending text notice only",
                    file_path.name,
                    size / (1024 * 1024),
                )
                send_message_to_telegram(
                    bot_token,
                    chat_id,
                    _oversize_notice(caption, file_path.name, size, note="413 from API"),
                )
                continue
            raise


def _oversize_notice(caption: str, filename: str, size_bytes: int, note: str = "") -> str:
    mib = size_bytes / (1024 * 1024)
    extra = f" ({note})" if note else ""
    base = caption or "Attachment"
    return (
        f"{base}\n"
        f"File too large for Telegram sendDocument (~50 MiB max){extra}: "
        f"{filename} ({mib:.1f} MiB)."
    )


def send_message_to_telegram(bot_token: str, chat_id: str, message: str) -> None:
    if not bot_token or not chat_id or not message.strip():
        return

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    response = requests.post(
        api_url,
        data={"chat_id": chat_id, "text": message.strip()},
        timeout=30,
    )
    response.raise_for_status()
