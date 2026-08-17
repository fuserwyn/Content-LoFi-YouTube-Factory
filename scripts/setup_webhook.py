"""Регистрация вебхука бота в Telegram.

Запускается внутри контейнера, где токен и секрет уже лежат в окружении —
так их значения не проходят через терминал и не оседают в истории команд.

    python scripts/setup_webhook.py          # зарегистрировать
    python scripts/setup_webhook.py --info   # показать текущее состояние
    python scripts/setup_webhook.py --delete # снять вебхук

Адрес берётся из RAILWAY_PUBLIC_DOMAIN, который Railway подставляет сам.
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from src.bot import WEBHOOK_PATH  # noqa: E402


def _api(token: str, method: str, **params) -> dict:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=30
    )
    return response.json()


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()

    if not token:
        print("TELEGRAM_BOT_TOKEN не задан")
        return 1

    if "--info" in sys.argv:
        info = _api(token, "getWebhookInfo").get("result") or {}
        print(f"адрес           : {info.get('url') or '(не задан)'}")
        print(f"ожидает апдейтов: {info.get('pending_update_count')}")
        print(f"секрет проверяется: {bool(info.get('has_custom_certificate') is not None and info.get('url'))}")
        if info.get("last_error_message"):
            print(f"последняя ошибка: {info['last_error_message']}")
        return 0

    if "--delete" in sys.argv:
        result = _api(token, "deleteWebhook", drop_pending_updates=True)
        print("вебхук снят" if result.get("ok") else f"не вышло: {result}")
        return 0 if result.get("ok") else 1

    # Без секрета вебхук принимал бы апдейты от кого угодно, кто узнал адрес,
    # а сам обработчик такие запросы отвергает — регистрировать бессмысленно.
    if not secret:
        print("TELEGRAM_WEBHOOK_SECRET не задан — регистрировать вебхук нельзя")
        return 1
    if not domain:
        print("RAILWAY_PUBLIC_DOMAIN пуст — у сервиса нет публичного адреса")
        return 1

    url = f"https://{domain}{WEBHOOK_PATH}"
    result = _api(
        token,
        "setWebhook",
        url=url,
        secret_token=secret,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )
    if not result.get("ok"):
        print(f"не вышло: {result.get('description')}")
        return 1

    print(f"вебхук зарегистрирован: {url}")
    info = _api(token, "getWebhookInfo").get("result") or {}
    print(f"Telegram подтверждает адрес: {info.get('url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
