from src.fetch_assets import _choose_file


def test_choose_file_returns_best_landscape_match() -> None:
    files = [
        {"width": 1280, "height": 720, "link": "low"},
        {"width": 1920, "height": 1080, "link": "fullhd"},
        {"width": 2560, "height": 1440, "link": "qhd"},
    ]
    chosen = _choose_file(files, min_width=1920, min_height=1080)
    assert chosen is not None
    assert chosen["link"] == "qhd"


def test_choose_file_rejects_portrait_and_small() -> None:
    files = [
        {"width": 1080, "height": 1920, "link": "portrait"},
        {"width": 1280, "height": 720, "link": "small"},
    ]
    chosen = _choose_file(files, min_width=1920, min_height=1080)
    assert chosen is None
