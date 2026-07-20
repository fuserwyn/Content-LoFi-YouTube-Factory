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
    youtube = MagicMock()
    youtube.channels().list().execute.return_value = {
        "items": [
            {
                "id": "UCtest123",
                "snippet": {"title": "LoFi Travel", "customUrl": "@lofitravel"},
            }
        ]
    }
    with patch("google.oauth2.credentials.Credentials", return_value=creds):
        with patch("google.auth.transport.requests.Request"):
            with patch("googleapiclient.discovery.build", return_value=youtube):
                ok, msg = probe_youtube_refresh_token("id", "sec", "refresh_abc")
    assert ok is True
    assert "LoFi Travel" in msg
    creds.refresh.assert_called_once()


def test_probe_config_profile_returns_channel() -> None:
    cfg = _minimal_config()
    with patch(
        "src.youtube_oauth_health._fetch_mine_channel",
        return_value=(
            True,
            "uploads go to channel: LoFi Travel",
            {
                "channel_id": "UCtest123",
                "channel_title": "LoFi Travel",
                "channel_custom_url": "@lofitravel",
            },
        ),
    ):
        result = probe_config_profile(cfg, None)
    assert result.ok is True
    assert result.token_source == "env"
    assert result.channel_id == "UCtest123"
    assert result.channel_title == "LoFi Travel"
