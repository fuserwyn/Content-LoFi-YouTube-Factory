"""Сборка ASS-субтитров под вертикальный формат.

Формат именно ASS, а не SRT: нужен контроль кегля, обводки и позиции. В шортсе
подпись должна читаться с телефона и не попадать под интерфейс плеера, поэтому
строки короткие, шрифт крупный, обводка толстая.

Слова группируются в реплики по 2-4 штуки и рвутся на паузах — так подпись идёт
в такт речи, а не висит абзацем на весь клип.
"""

from __future__ import annotations

from dataclasses import dataclass

from .transcribe import Word

# DejaVu приезжает вместе с ffmpeg в образе и покрывает кириллицу.
DEFAULT_FONT = "DejaVu Sans"

MAX_WORDS_PER_CUE = 4
MAX_CHARS_PER_CUE = 32
MAX_CUE_MS = 2500
# Пауза длиннее этой рвёт реплику, даже если слов набралось мало.
GAP_SPLIT_MS = 450
MIN_CUE_MS = 400


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str


def _escape(text: str) -> str:
    """В ASS фигурные скобки открывают блок команд, а бэкслеш экранирует."""
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", " ")
    )


def _timestamp(ms: int) -> str:
    ms = max(0, ms)
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{millis // 10:02d}"


def group_words(words: list[Word]) -> list[Cue]:
    """Режет поток слов на короткие реплики по паузам, длине и числу слов."""
    cues: list[Cue] = []
    bucket: list[Word] = []

    def flush() -> None:
        if not bucket:
            return
        text = " ".join(w.text for w in bucket).strip()
        if text:
            start = bucket[0].start_ms
            end = max(bucket[-1].end_ms, start + MIN_CUE_MS)
            cues.append(Cue(start_ms=start, end_ms=end, text=text))
        bucket.clear()

    for word in words:
        if bucket:
            gap = word.start_ms - bucket[-1].end_ms
            pending = " ".join(w.text for w in bucket)
            too_long = word.end_ms - bucket[0].start_ms > MAX_CUE_MS
            too_many = len(bucket) >= MAX_WORDS_PER_CUE
            too_wide = len(pending) + 1 + len(word.text) > MAX_CHARS_PER_CUE
            if gap >= GAP_SPLIT_MS or too_long or too_many or too_wide:
                flush()
        bucket.append(word)

    flush()

    # Реплики не должны перекрываться — иначе libass покажет их одновременно.
    for earlier, later in zip(cues, cues[1:]):
        if earlier.end_ms > later.start_ms:
            earlier.end_ms = later.start_ms
    return [c for c in cues if c.end_ms > c.start_ms]


def window_words(words: list[Word], start_ms: int, end_ms: int) -> list[Word]:
    """Слова, попадающие в окно клипа, со сдвигом таймкодов к нулю клипа."""
    picked: list[Word] = []
    for word in words:
        if word.end_ms <= start_ms or word.start_ms >= end_ms:
            continue
        picked.append(
            Word(
                start_ms=max(0, word.start_ms - start_ms),
                end_ms=min(end_ms, word.end_ms) - start_ms,
                text=word.text,
            )
        )
    return picked


def build_ass(
    words: list[Word],
    width: int,
    height: int,
    font: str = DEFAULT_FONT,
    font_size: int = 0,
    margin_v: int = 0,
) -> str:
    """ASS-документ для клипа. ``words`` уже должны быть сдвинуты к началу клипа."""
    # Кегль и отступ от низа считаем от высоты кадра, чтобы вёрстка не поехала
    # при смене разрешения. Отступ поднимает текст над плашкой плеера.
    size = font_size or max(24, height // 22)
    bottom = margin_v or int(height * 0.18)
    side = int(width * 0.06)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(2, size // 12)},2,2,{side},{side},{bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""

    lines = [
        f"Dialogue: 0,{_timestamp(cue.start_ms)},{_timestamp(cue.end_ms)},Default,,0,0,0,,{_escape(cue.text)}"
        for cue in group_words(words)
    ]
    return header + "\n".join(lines) + "\n"
