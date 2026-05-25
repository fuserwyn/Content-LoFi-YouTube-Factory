"""Tests for YouTube OAuth refresh probe."""

from unittest.mock import MagicMock, patch

from test_youtube_oauth_resolve import _minimal_config

from src.youtube_oauth_health import probe_config_profile, probe_youtube_refresh_token


def test_probe_empty_refresh() -> None:
    ok, msg = probe_youtube_refresh_token("id", "sec", "")
    assert ok is False
    assert "empty" in msg.lower()


def test_probe_success() -> None:
    creds = MagicMock()
    creds.token = "access_xyz"
    with patch("google.oauth2.credentials.Credentials", return_value=creds):
        with patch("google.auth.transport.requests.Request"):
            ok, msg = probe_youtube_refresh_token("id", "sec", "refresh_abc")
    assert ok is True
    creds.refresh.assert_called_once()


def test_probe_config_profile_uses_env() -> None:
    cfg = _minimal_config()
    with patch(
        "src.youtube_oauth_health.probe_youtube_refresh_token",
        return_value=(True, "ok"),
    ):
        result = probe_config_profile(cfg, None)
    assert result.ok is True
    assert result.token_source == "env"
