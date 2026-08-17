"""Проверка живых внешних API — Telegram и Claude.

Запускается внутри контейнера, где ключи уже лежат в окружении: значения
секретов никуда не выводятся, наружу идут только имя бота и результат отбора.

    python scripts/smoke_live_apis.py

Смысл в том, чтобы подтвердить форму запросов на реальных вызовах. Юнит-тесты
мокают клиентов и поэтому не поймают ни неверное поле, ни отозванный токен.
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from src.highlights import find_highlights  # noqa: E402
from src.transcribe import TranscriptSegment, Word  # noqa: E402

# Короткий синтетический транскрипт: один кусок явно сильнее остальных,
# так что осмысленный отбор обязан выбрать именно его.
TRANSCRIPT = [
    (0, 25_000, "Всем привет, меня зовут Иван, сегодня у нас выпуск про монтаж, "
                "садитесь поудобнее, сейчас всё расскажу."),
    (25_000, 55_000, "Мы три года считали, что длинные видео надо продвигать целиком. "
                     "Оказалось, это была главная ошибка: канал вырос в двадцать раз "
                     "только после того, как мы начали резать их на короткие ролики."),
    (55_000, 85_000, "Ну и там ещё по мелочи, всякие настройки, о них потом как-нибудь."),
]


def _segments() -> list[TranscriptSegment]:
    segments = []
    for start, end, text in TRANSCRIPT:
        words = text.split()
        step = (end - start) // max(1, len(words))
        segments.append(
            TranscriptSegment(
                start_ms=start,
                end_ms=end,
                text=text,
                words=[
                    Word(start + i * step, start + (i + 1) * step, w)
                    for i, w in enumerate(words)
                ],
            )
        )
    return segments


def check_telegram() -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("  ПРОВАЛ TELEGRAM_BOT_TOKEN не задан")
        return False
    try:
        payload = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=20
        ).json()
    except requests.RequestException as exc:
        print(f"  ПРОВАЛ Telegram недоступен: {exc}")
        return False
    if not payload.get("ok"):
        # Описание ошибки безопасно: токен в него не попадает.
        print(f"  ПРОВАЛ Telegram отверг токен: {payload.get('description')}")
        return False
    bot = payload.get("result") or {}
    print(f"  OK   бот @{bot.get('username')} (id {bot.get('id')}), имя «{bot.get('first_name')}»")
    return True


def check_claude() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        print("  ПРОВАЛ ANTHROPIC_API_KEY не задан")
        return False
    try:
        found = find_highlights(
            _segments(),
            source_duration_ms=85_000,
            max_count=2,
            min_seconds=20,
            max_seconds=45,
        )
    except Exception as exc:  # noqa: BLE001 — здесь важен сам факт сбоя
        print(f"  ПРОВАЛ вызов Claude не прошёл: {exc}")
        return False

    if not found:
        print("  ПРОВАЛ Claude ответил, но не выбрал ни одного фрагмента")
        return False

    print(f"  OK   Claude вернул {len(found)} фрагмент(ов):")
    for h in found:
        print(f"         [{h.start_ms}-{h.end_ms}] score={h.score:.2f} «{h.title}»")
        print(f"           {h.reason}")

    # Осмысленность отбора: сильный кусок — второй, с 25-й по 55-ю секунду.
    best = max(found, key=lambda h: h.score)
    hit = best.start_ms < 55_000 and best.end_ms > 25_000
    print(f"  {'OK  ' if hit else 'ПРОВАЛ'} лучший фрагмент попал в содержательную часть")
    return hit


def main() -> int:
    print("Telegram:")
    telegram_ok = check_telegram()
    print("\nClaude:")
    claude_ok = check_claude()

    if telegram_ok and claude_ok:
        print("\nобе проверки прошли")
        return 0
    print("\nесть провалы")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
