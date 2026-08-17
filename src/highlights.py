"""Отбор хайлайтов из транскрипта — ядро продукта.

Нарезать по таймкодам умеет любой ffmpeg; ценность в том, чтобы попасть в
моменты, которые досматривают. Здесь этим занимается Claude: он читает
транскрипт с таймкодами и возвращает окна, каждое со скором и обоснованием.

Обоснование (``reason``) нужно не модели, а нам — по нему видно, почему отбор
промахнулся, и что чинить в промпте. Без него качество отладить нечем.

Ответ приходит через structured outputs, то есть валидность JSON гарантирует
API — парсить свободный текст и городить retry-циклы не требуется.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

import anthropic

from .transcribe import TranscriptSegment

MODEL = "claude-opus-5"

# На Opus 5 мышление включено по умолчанию, а max_tokens ограничивает мышление
# и ответ вместе. Запас нужен, иначе ответ обрежется на середине JSON.
MAX_TOKENS = 16000

# Серверный резерв: если классификаторы Opus 5 отклонят запрос, API сам
# переигрывает его на другой модели в рамках того же вызова. Без этого отказ
# останавливал бы конвейер там, где он способен восстановиться сам.
# "default" — маршрутизация по категории отказа, чтобы не поддерживать
# список моделей руками.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

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
    model: str = MODEL,
    effort: str = "high",
) -> list[Highlight]:
    """Возвращает непересекающиеся окна по убыванию скора, не длиннее ``max_count``.

    ``api_key`` можно не передавать — SDK сам возьмёт ANTHROPIC_API_KEY из окружения.
    """
    if not segments:
        return []

    min_ms, max_ms = min_seconds * 1000, max_seconds * 1000
    client = anthropic.Anthropic(api_key=api_key) if api_key.strip() else anthropic.Anthropic()

    instruction = (
        f"Ниже транскрипт видео длительностью {source_duration_ms // 1000} секунд. "
        f"Каждая строка — реплика в формате [начало-конец в миллисекундах] текст.\n\n"
        f"Отбери до {max_count} фрагментов длительностью от {min_seconds} до "
        f"{max_seconds} секунд. Фрагменты не должны пересекаться.\n\n"
        f"{render_transcript(segments)}"
    )

    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": _SCHEMA},
            },
            messages=[{"role": "user", "content": instruction}],
        )
    except anthropic.APIStatusError as exc:
        raise HighlightError(f"Claude API {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise HighlightError("Не удалось соединиться с Claude API") from exc

    # Сюда попадаем, только если отказала вся цепочка вместе с резервом —
    # тогда content пустой или обрезанный, и читать его по индексу нельзя.
    if response.stop_reason == "refusal":
        raise HighlightError("Отбор хайлайтов отклонён и основной моделью, и резервной")
    if response.stop_reason == "max_tokens":
        raise HighlightError("Ответ обрезан по max_tokens — JSON неполный")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text.strip():
        raise HighlightError("Claude вернул пустой ответ")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HighlightError("Claude вернул невалидный JSON") from exc

    return _parse(payload, source_duration_ms, min_ms, max_ms)[:max_count]
