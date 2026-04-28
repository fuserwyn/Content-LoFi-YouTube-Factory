import os

import pytest

from src.config import _parse_bool, load_config


REQUIRED_ENV = {
    "PEXELS_API_KEY": "test_pexels",
    "YOUTUBE_CLIENT_ID": "test_client_id",
    "YOUTUBE_CLIENT_SECRET": "test_client_secret",
    "YOUTUBE_REFRESH_TOKEN": "test_refresh",
}


def test_parse_bool_true_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_ENABLED", "yes")
    assert _parse_bool("UPLOAD_ENABLED", False) is True


def test_load_config_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REQUIRED_ENV:
        monkeypatch.setenv(key, "")

    with pytest.raises(ValueError):
        load_config()


def test_load_config_success(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("CONTENT_TAGS", "nature,surf")
    monkeypatch.setenv("UPLOAD_ENABLED", "false")

    config = load_config()

    assert config.pexels_api_key == "test_pexels"
    assert config.content_tags == ["nature", "surf"]
    assert config.upload_enabled is False
    assert os.path.isdir(config.assets_tracks_dir)
