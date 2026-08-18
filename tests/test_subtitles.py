from src.subtitles import Cue, build_ass, group_words, window_words
from src.transcribe import Word


def test_group_words_splits_on_pause() -> None:
    words = [
        Word(0, 400, "раз"),
        Word(420, 800, "два"),
        Word(1900, 2300, "три"),
    ]

    cues = group_words(words)

    assert len(cues) == 2
    assert cues[0].text == "раз два"
    assert cues[1].text == "три"


def test_group_words_caps_words_per_cue() -> None:
    words = [Word(i * 200, i * 200 + 150, "a") for i in range(9)]

    cues = group_words(words)

    assert all(len(cue.text.split()) <= 4 for cue in cues)


def test_group_words_caps_cue_duration() -> None:
    words = [Word(i * 900, i * 900 + 800, "слово") for i in range(4)]

    cues = group_words(words)

    assert all(cue.end_ms - cue.start_ms <= 2500 for cue in cues)


def test_group_words_returns_empty_for_no_words() -> None:
    assert group_words([]) == []


def test_group_words_cues_do_not_overlap() -> None:
    words = [Word(i * 300, i * 300 + 290, f"w{i}") for i in range(12)]

    cues = group_words(words)

    for earlier, later in zip(cues, cues[1:]):
        assert earlier.end_ms <= later.start_ms


def test_window_words_shifts_timestamps_to_clip_start() -> None:
    words = [Word(5000, 5400, "внутри"), Word(9000, 9400, "снаружи")]

    picked = window_words(words, 4800, 6000)

    assert len(picked) == 1
    assert picked[0].text == "внутри"
    assert picked[0].start_ms == 200


def test_window_words_clamps_word_crossing_the_end() -> None:
    words = [Word(1000, 3000, "длинное")]

    picked = window_words(words, 0, 2000)

    assert picked[0].end_ms == 2000


def test_window_words_drops_words_outside_window() -> None:
    words = [Word(0, 500, "до"), Word(9000, 9500, "после")]

    assert window_words(words, 2000, 4000) == []


def test_build_ass_has_header_and_dialogue_lines() -> None:
    words = [Word(0, 500, "привет"), Word(1200, 1700, "мир")]

    ass = build_ass(words, 1080, 1920)

    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert ass.count("Dialogue:") == 2


def test_build_ass_scales_font_to_frame_size() -> None:
    words = [Word(0, 500, "тест")]

    small = build_ass(words, 540, 960)
    large = build_ass(words, 1080, 1920)

    assert "DejaVu Sans,40" in small
    assert "DejaVu Sans,80" in large


def test_build_ass_escapes_brace_syntax() -> None:
    # В ASS фигурные скобки открывают блок команд — неэкранированные сломают рендер.
    words = [Word(0, 500, "{drop}")]

    ass = build_ass(words, 1080, 1920)

    assert "\\{drop\\}" in ass


def test_build_ass_without_words_yields_no_dialogue() -> None:
    ass = build_ass([], 1080, 1920)

    assert "Dialogue:" not in ass
    assert "[Events]" in ass


def test_cue_does_not_open_with_punctuation() -> None:
    # Whisper отдаёт знак отдельным токеном; реплика, начавшаяся с него,
    # читается как обрывок предыдущей фразы.
    words = [Word(0, 100, ","), Word(120, 600, "сделали"), Word(650, 1000, "Мы")]

    cues = group_words(words)

    assert cues[0].text == "сделали Мы"


def test_punctuation_glued_to_a_word_survives() -> None:
    # Убирать надо только ведущий знак, а не пунктуацию внутри реплики.
    words = [Word(0, 500, "сделали."), Word(600, 900, "Мы")]

    cues = group_words(words)

    assert "сделали." in cues[0].text


def test_cue_of_only_punctuation_is_dropped() -> None:
    words = [Word(0, 100, ","), Word(200, 300, "—")]

    assert group_words(words) == []


def test_no_cue_opens_with_a_comma_however_whisper_splits_it() -> None:
    # Три способа, которыми Whisper отдаёт запятую на границе фразы. Ни один
    # не должен оставить её в начале реплики — это читается как обрывок.
    variants = [
        [Word(0, 100, ","), Word(120, 600, "миллионов."), Word(650, 1000, "У")],
        [Word(0, 600, ",миллионов."), Word(650, 1000, "У")],
        [Word(0, 500, "десять,"), Word(520, 900, "миллионов.")],
    ]

    for words in variants:
        for cue in group_words(words):
            assert not cue.text.lstrip().startswith(",")
