"""Отбор хайлайтов из транскрипта — ядро продукта.

Нарезать по таймкодам умеет любой ffmpeg; ценность в том, чтобы попасть в
моменты, которые досматривают. Здесь этим занимается Claude: он читает
транскрипт с таймкодами и возвращает окна, каждое со скором и обоснованием.

Обоснование (``reason``) нужно не модели, а нам — по нему видно, почему отбор
промахнулся, и что чинить в промпте. Без него качество отладить нечем.

Ответ приходит через structured outputs, то есть валидность JSON гарантирует
API — парсить свободный текст и городить retry-циклы не требуется.

Ходим через OpenRouter: один ключ и один баланс на все внешние модели, без
отдельного биллинга и без протухающих OAuth-токенов. Opus 5 стоит там столько
же, сколько напрямую, так что на качестве отбора это не экономия и не потеря.
Цена — ещё один обработчик данных на пути клиентских транскриптов; это
осознанный выбор, а не недосмотр.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os

import requests

from .transcribe import TranscriptSegment

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Модель вынесена в окружение, чтобы сравнивать варианты на своём контенте без
# передеплоя: OPENROUTER_MODEL переключает её одной командой.
#
# Цена за одно двухчасовое видео (транскрипт ~21K токенов на вход):
#   бесплатные модели        $0
#   anthropic/claude-haiku-4.5    $0.031   <- выбрано
#   anthropic/claude-sonnet-4.6   $0.093
#   anthropic/claude-opus-5       $0.155
#
# Задача здесь не извлечение фактов, а суждение о том, какой момент зацепит
# зрителя, и на таком слабые модели проваливаются заметнее всего. Насколько
# именно — проверяется на первом же настоящем видео; если отбор начнёт
# попадать в приветствия вместо содержания, поднимать модель до sonnet или opus.
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

# Резерв: OpenRouter пробует модели по порядку, если предыдущая недоступна
# или отклонила запрос. Заменяет серверный fallbacks, которого тут нет.
DEFAULT_FALLBACKS = ["anthropic/claude-sonnet-4.6"]


def _model_from_env() -> str:
    return os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL


def _fallbacks_from_env() -> list[str]:
    raw = os.getenv("OPENROUTER_FALLBACK_MODELS", "").strip()
    if not raw:
        return list(DEFAULT_FALLBACKS)
    return [m.strip() for m in raw.split(",") if m.strip()]

# Мышление у Opus 5 включено по умолчанию и делит лимит с ответом.
# Запас нужен, иначе ответ обрежется на середине JSON.
MAX_TOKENS = 16000

REQUEST_TIMEOUT = 300

DEFAULT_MIN_SECONDS = 20
DEFAULT_MAX_SECONDS = 60
DEFAULT_MAX_COUNT = 10

_SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_ms": {
                        "type": "integer",
                        "description": "Начало окна в миллисекундах от начала видео.",
                    },
                    "end_ms": {
                        "type": "integer",
                        "description": "Конец окна в миллисекундах от начала видео.",
                    },
                    "score": {
                        "type": "number",
                        "description": "Насколько сильный момент, от 0 до 1.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Короткий заголовок шортса, до 60 символов.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Чем этот момент цепляет — одним предложением.",
                    },
                },
                "required": ["start_ms", "end_ms", "score", "title", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["highlights"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
Ты отбираешь фрагменты длинного видео, из которых получатся самостоятельные шортсы.

Шортс смотрят без контекста и решают за первые секунды, оставаться или листать \
дальше. Поэтому фрагмент должен быть понятен человеку, который не видел остального \
видео, и начинаться с того, что удерживает внимание — с утверждения, вопроса, \
неожиданного поворота, а не с разгона и представлений.

Что обычно работает: законченная мысль или история с началом и концом; конкретное \
мнение, с которым можно спорить; момент, где говорящий меняет позицию или признаёт \
неожиданное; практический совет, который можно применить сразу.

Что обычно не работает: приветствия и подводки, обсуждение регламента разговора, \
фрагменты, смысл которых держится на том, что было сказано раньше, и перечисления \
без вывода.

Границы фрагмента ставь по краям реплик из транскрипта — обрыв на середине фразы \
портит шортс сильнее, чем неидеальный выбор темы.

Оценивай честно: если в видео нашлось три сильных момента, верни три. Заполнять \
лимит слабыми фрагментами не нужно — их всё равно никто не досмотрит."""


@dataclass
class Highlight:
    start_ms: int
    end_ms: int
    score: float
    title: str
    reason: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class HighlightError(RuntimeError):
    pass


def render_transcript(segments: list[TranscriptSegment]) -> str:
    """Транскрипт с таймкодами — по строке на реплику, чтобы модель могла ссылаться
    на реальные границы, а не выдумывать их."""
    return "\n".join(f"[{s.start_ms}-{s.end_ms}] {s.text}" for s in segments)


def _drop_overlaps(highlights: list[Highlight]) -> list[Highlight]:
    """Пересекающиеся окна дали бы два шортса с одним и тем же куском.
    Идём по убыванию скора и оставляем непересекающиеся."""
    kept: list[Highlight] = []
    for candidate in sorted(highlights, key=lambda h: h.score, reverse=True):
        if any(
            candidate.start_ms < k.end_ms and k.start_ms < candidate.end_ms
            for k in kept
        ):
            continue
        kept.append(candidate)
    return kept


def _parse(payload: dict, source_duration_ms: int, min_ms: int, max_ms: int) -> list[Highlight]:
    found: list[Highlight] = []
    for raw in payload.get("highlights") or []:
        try:
            start = max(0, int(raw["start_ms"]))
            end = min(source_duration_ms, int(raw["end_ms"]))
            score = float(raw["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not min_ms <= end - start <= max_ms:
            continue
        found.append(
            Highlight(
                start_ms=start,
                end_ms=end,
                # Схема structured outputs не поддерживает minimum/maximum,
                # поэтому диапазон скора подрезаем здесь.
                score=min(1.0, max(0.0, score)),
                title=str(raw.get("title", "")).strip(),
                reason=str(raw.get("reason", "")).strip(),
            )
        )
    return _drop_overlaps(found)


def find_highlights(
    segments: list[TranscriptSegment],
    source_duration_ms: int,
    api_key: str = "",
    *,
    max_count: int = DEFAULT_MAX_COUNT,
    min_seconds: int = DEFAULT_MIN_SECONDS,
    max_seconds: int = DEFAULT_MAX_SECONDS,
    model: str = "",
    effort: str = "high",
) -> list[Highlight]:
    """Возвращает непересекающиеся окна по убыванию скора, не длиннее ``max_count``.

    ``api_key`` и ``model`` можно не передавать: подхватятся ``OPENROUTER_API_KEY``
    и ``OPENROUTER_MODEL`` из окружения.
    """
    if not segments:
        return []

    key = api_key.strip() or os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise HighlightError("OPENROUTER_API_KEY не задан")

    model = model.strip() or _model_from_env()
    min_ms, max_ms = min_seconds * 1000, max_seconds * 1000

    instruction = (
        f"Ниже транскрипт видео длительностью {source_duration_ms // 1000} секунд. "
        f"Каждая строка — реплика в формате [начало-конец в миллисекундах] текст.\n\n"
        f"Отбери до {max_count} фрагментов длительностью от {min_seconds} до "
        f"{max_seconds} секунд. Фрагменты не должны пересекаться.\n\n"
        f"{render_transcript(segments)}"
    )

    body = {
        "model": model,
        # OpenRouter пойдёт по списку дальше, если модель недоступна или
        # отклонила запрос.
        "models": [model, *(m for m in _fallbacks_from_env() if m != model)],
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "highlights", "strict": True, "schema": _SCHEMA},
        },
        # Без этого запрос мог бы уехать на эндпоинт, который схему не
        # поддерживает, и вместо гарантированного JSON вернулся бы свободный
        # текст — ровно то, ради ухода от чего эта схема и заведена.
        "provider": {"require_parameters": True},
        "reasoning": {"effort": effort},
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise HighlightError(f"Не удалось соединиться с OpenRouter: {exc}") from exc

    if response.status_code != 200:
        raise HighlightError(f"OpenRouter {response.status_code}: {response.text[:300]}")

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise HighlightError("OpenRouter вернул не-JSON") from exc

    if payload.get("error"):
        raise HighlightError(f"OpenRouter: {payload['error']}")

    choices = payload.get("choices") or []
    if not choices:
        raise HighlightError("OpenRouter не вернул ни одного варианта ответа")

    choice = choices[0]
    message = choice.get("message") or {}

    # Отказ модели приходит отдельным полем, а не текстом — читать content
    # в этом случае бессмысленно.
    if message.get("refusal"):
        raise HighlightError(f"Модель отклонила запрос: {message['refusal']}")
    if choice.get("finish_reason") == "length":
        raise HighlightError("Ответ обрезан по max_tokens — JSON неполный")

    text = (message.get("content") or "").strip()
    if not text:
        raise HighlightError(
            f"Модель вернула пустой ответ (finish_reason={choice.get('finish_reason')}, "
            f"модель={payload.get('model')})"
        )

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # Показываем начало ответа: со structured outputs такого быть не должно,
        # и без образца непонятно, кто именно нарушил контракт — модель,
        # роутер или наш собственный запрос.
        raise HighlightError(
            f"Модель {payload.get('model')} вернула невалидный JSON: {text[:300]!r}"
        ) from exc

    return _parse(parsed, source_duration_ms, min_ms, max_ms)[:max_count]
