import os

import pytest

from src.config import _parse_bool, load_config


REQUIRED_ENV = {
    "YOUTUBE_CLIENT_ID": "test_client_id",
    "YOUTUBE_CLIENT_SECRET": "test_client_secret",
    "YOUTUBE_REFRESH_TOKEN": "test_refresh",
}


def _clear_youtube_channel_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent developer .env from affecting channel-related assertions."""
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHANNEL_ID", "")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "")
    monkeypatch.setenv("YOUTUBE_CONTENT_OWNER_ID", "")


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

    _clear_youtube_channel_env(monkeypatch)
    monkeypatch.setenv("CONTENT_TAGS", "nature,surf")
    monkeypatch.setenv("UPLOAD_ENABLED", "false")
    monkeypatch.setenv("PEXELS_API_KEY", "test_pexels")

    config = load_config()

    assert config.pexels_api_key == "test_pexels"
    assert config.content_tags == ["nature", "surf"]
    assert config.upload_enabled is False
    assert config.youtube_upload_channel_id == ""
    assert os.path.isdir(config.assets_tracks_dir)
    assert os.path.isdir(config.assets_source_videos_dir)
    assert config.run_mode == "oneshot"


def test_load_config_upload_channel_prefers_primary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    _clear_youtube_channel_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHANNEL_ID", "UC_primary")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC_legacy")

    config = load_config()
    assert config.youtube_upload_channel_id == "UC_primary"


def test_load_config_upload_channel_falls_back_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    _clear_youtube_channel_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHANNEL_ID", "")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC_legacy_only")

    config = load_config()
    assert config.youtube_upload_channel_id == "UC_legacy_only"


def test_load_config_rejects_invalid_run_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("RUN_MODE", "invalid")

    with pytest.raises(ValueError):
        load_config()
