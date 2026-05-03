"""Tests for multi-channel YouTube OAuth refresh selection."""

from pathlib import Path

import pytest

from src.config import AppConfig, resolve_youtube_refresh_token


def _minimal_config(**kwargs: str) -> AppConfig:
    base = dict(
        pexels_api_key="",
        youtube_client_id="id",
        youtube_client_secret="sec",
        youtube_refresh_token="primary_rt",
        youtube_refresh_token_alt="",
        youtube_upload_channel_id="",
        youtube_content_owner_id="",
        youtube_use_on_behalf_upload=False,
        youtube_upload_fallback_to_primary=True,
        youtube_default_privacy="private",
        youtube_category_id="10",
        youtube_default_language="en",
        target_duration_min=30,
        target_width=1920,
        target_height=1080,
        fps=30,
        max_clips_per_run=20,
        min_clip_seconds=5,
        max_recent_track_lookback=10,
        max_recent_clip_lookback=100,
        content_tags=[],
        upload_enabled=False,
        publish_at_iso="",
        assets_tracks_dir=Path("/tmp"),
        temp_clips_dir=Path("/tmp"),
        temp_renders_dir=Path("/tmp"),
        data_dir=Path("/tmp"),
        runs_dir=Path("/tmp"),
        state_db_path=Path("/tmp/db"),
        database_url="",
        pexels_per_page=30,
        pexels_pages_per_tag=2,
        n8n_webhook_url="",
        cleanup_temp_after_run=True,
        keep_final_output=False,
        render_preset="fast",
        render_crf=23,
        use_local_videos_only=False,
        local_videos_fallback_to_pexels=True,
        assets_source_videos_dir=Path("/tmp"),
        run_mode="oneshot",
        trigger_api_key="",
        no_repeat_clips_in_single_video=False,
        allow_shorter_unique_video=True,
        match_video_duration_to_track=False,
        tiktok_cuts_enabled=False,
        tiktok_clips_per_run=3,
        tiktok_clip_seconds=30,
        tiktok_width=1080,
        tiktok_height=1920,
        tiktok_output_dir=Path("/tmp"),
        telegram_send_tiktok=False,
        telegram_bot_token="",
        telegram_chat_id="",
        telegram_api_id=0,
        telegram_api_hash="",
        telegram_session_string="",
        poyo_api_key="",
        poyo_api_base_url="",
        poyo_generate_path="",
        poyo_status_path_template="",
        poyo_download_url_field="",
        poyo_id_field="",
        poyo_status_field="",
        poyo_ready_statuses=[],
        poyo_failed_statuses=[],
        poyo_poll_interval_seconds=5,
        poyo_max_wait_seconds=60,
        video_generation_provider="poyo",
        minimax_api_key="",
        minimax_api_base_url="https://api.minimax.io",
        minimax_video_model="MiniMax-Hailuo-02",
        minimax_video_duration=10,
        minimax_video_resolution="768P",
        minimax_poll_interval_seconds=10,
        minimax_max_wait_seconds=600,
    )
    base.update(kwargs)
    return AppConfig(**base)  # type: ignore[arg-type]


def test_resolve_default_and_none() -> None:
    cfg = _minimal_config()
    assert resolve_youtube_refresh_token(cfg, None) == "primary_rt"
    assert resolve_youtube_refresh_token(cfg, "default") == "primary_rt"
    assert resolve_youtube_refresh_token(cfg, "PRIMARY") == "primary_rt"


def test_resolve_alt_requires_env() -> None:
    cfg = _minimal_config()
    with pytest.raises(ValueError, match="YOUTUBE_REFRESH_TOKEN_ALT"):
        resolve_youtube_refresh_token(cfg, "alt")


def test_resolve_alt_ok() -> None:
    cfg = _minimal_config(youtube_refresh_token_alt=" alt_rt ")
    assert resolve_youtube_refresh_token(cfg, "2") == "alt_rt"
    assert resolve_youtube_refresh_token(cfg, "secondary") == "alt_rt"
