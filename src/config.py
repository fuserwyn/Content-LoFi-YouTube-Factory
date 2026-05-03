from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


_DEFAULT_YOUTUBE_OAUTH_PROFILES = frozenset({"", "default", "primary", "main", "1"})
_ALT_YOUTUBE_OAUTH_PROFILES = frozenset({"alt", "secondary", "second", "2", "channel2", "other"})


@dataclass
class AppConfig:
    pexels_api_key: str
    youtube_client_id: str
    youtube_client_secret: str
    youtube_refresh_token: str
    youtube_refresh_token_alt: str
    youtube_upload_channel_id: str
    youtube_content_owner_id: str
    youtube_use_on_behalf_upload: bool
    youtube_upload_fallback_to_primary: bool
    youtube_default_privacy: str
    youtube_category_id: str
    youtube_default_language: str
    target_duration_min: int
    target_width: int
    target_height: int
    fps: int
    max_clips_per_run: int
    min_clip_seconds: int
    max_recent_track_lookback: int
    max_recent_clip_lookback: int
    content_tags: list[str]
    upload_enabled: bool
    publish_at_iso: str
    assets_tracks_dir: Path
    temp_clips_dir: Path
    temp_renders_dir: Path
    data_dir: Path
    runs_dir: Path
    state_db_path: Path
    database_url: str
    pexels_per_page: int
    pexels_pages_per_tag: int
    n8n_webhook_url: str
    cleanup_temp_after_run: bool
    keep_final_output: bool
    render_preset: str
    render_crf: int
    use_local_videos_only: bool
    local_videos_fallback_to_pexels: bool
    assets_source_videos_dir: Path
    run_mode: str
    trigger_api_key: str
    no_repeat_clips_in_single_video: bool
    allow_shorter_unique_video: bool
    match_video_duration_to_track: bool
    tiktok_cuts_enabled: bool
    tiktok_clips_per_run: int
    tiktok_clip_seconds: int
    tiktok_width: int
    tiktok_height: int
    tiktok_output_dir: Path
    telegram_send_tiktok: bool
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_api_id: int
    telegram_api_hash: str
    telegram_session_string: str
    poyo_api_key: str
    poyo_api_base_url: str
    poyo_generate_path: str
    poyo_status_path_template: str
    poyo_download_url_field: str
    poyo_id_field: str
    poyo_status_field: str
    poyo_ready_statuses: list[str]
    poyo_failed_statuses: list[str]
    poyo_poll_interval_seconds: int
    poyo_max_wait_seconds: int
    video_generation_provider: str
    minimax_api_key: str
    minimax_api_base_url: str
    minimax_video_model: str
    minimax_video_duration: int
    minimax_video_resolution: str
    minimax_poll_interval_seconds: int
    minimax_max_wait_seconds: int


def _require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing required env var: {name}")
    return value


def _parse_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_youtube_refresh_token(config: AppConfig, profile: str | None) -> str:
    """Pick refresh token for multi-channel uploads in one process.

    * default / omitted / primary → ``YOUTUBE_REFRESH_TOKEN``
    * alt / secondary / 2 / … → ``YOUTUBE_REFRESH_TOKEN_ALT``
    """
    raw = profile.strip() if isinstance(profile, str) else ""
    key = (raw or "default").strip().lower()
    if key in _DEFAULT_YOUTUBE_OAUTH_PROFILES:
        return config.youtube_refresh_token.strip()
    if key in _ALT_YOUTUBE_OAUTH_PROFILES:
        alt = (config.youtube_refresh_token_alt or "").strip()
        if not alt:
            raise ValueError(
                "youtube_oauth_profile is 'alt' but YOUTUBE_REFRESH_TOKEN_ALT is empty"
            )
        return alt
    raise ValueError(
        f"Invalid youtube_oauth_profile {profile!r}; use 'default' or 'alt' (or omit for default)"
    )


def _env_with_fallback(primary: str, fallback: str, default: str) -> str:
    value = os.getenv(primary)
    if value is not None and value.strip() != "":
        return value.strip()
    legacy = os.getenv(fallback)
    if legacy is not None and legacy.strip() != "":
        return legacy.strip()
    return default


def load_config() -> AppConfig:
    load_dotenv()

    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"
    runs_dir = data_dir / "runs"
    assets_tracks_dir = project_root / "assets" / "tracks"
    assets_source_videos_dir = project_root / "assets" / "source_videos"
    temp_clips_dir = project_root / "temp" / "clips"
    temp_renders_dir = project_root / "temp" / "renders"
    tiktok_output_dir = data_dir / "tiktok"
    state_db_path = data_dir / "state.db"

    for path in [
        data_dir,
        runs_dir,
        assets_tracks_dir,
        assets_source_videos_dir,
        temp_clips_dir,
        temp_renders_dir,
        tiktok_output_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    tags_raw = os.getenv("CONTENT_TAGS", "nature,surf,ocean,sunset")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    run_mode = os.getenv("RUN_MODE", "oneshot").strip().lower() or "oneshot"
    if run_mode not in {"oneshot", "webhook"}:
        raise ValueError("RUN_MODE must be either 'oneshot' or 'webhook'")

    video_generation_provider = os.getenv("VIDEO_GENERATION_PROVIDER", "poyo").strip().lower() or "poyo"
    if video_generation_provider not in {"poyo", "minimax"}:
        raise ValueError("VIDEO_GENERATION_PROVIDER must be either 'poyo' or 'minimax'")

    resolved_tiktok_output_dir = Path(os.getenv("TIKTOK_OUTPUT_DIR", str(tiktok_output_dir)))
    resolved_tiktok_output_dir.mkdir(parents=True, exist_ok=True)
    poyo_ready_statuses = [
        item.strip().lower()
        for item in _env_with_fallback(
            "POYO_SEEDANCE_READY_STATUSES",
            "POYO_READY_STATUSES",
            "finished,completed,succeeded,ready",
        ).split(",")
        if item.strip()
    ]
    poyo_failed_statuses = [
        item.strip().lower()
        for item in _env_with_fallback(
            "POYO_SEEDANCE_FAILED_STATUSES",
            "POYO_FAILED_STATUSES",
            "failed,error,cancelled",
        ).split(",")
        if item.strip()
    ]

    return AppConfig(
        pexels_api_key=os.getenv("PEXELS_API_KEY", "").strip(),
        youtube_client_id=_require_env("YOUTUBE_CLIENT_ID"),
        youtube_client_secret=_require_env("YOUTUBE_CLIENT_SECRET"),
        youtube_refresh_token=_require_env("YOUTUBE_REFRESH_TOKEN"),
        youtube_refresh_token_alt=os.getenv("YOUTUBE_REFRESH_TOKEN_ALT", "").strip(),
        youtube_upload_channel_id=_env_with_fallback(
            "YOUTUBE_UPLOAD_CHANNEL_ID",
            "YOUTUBE_CHANNEL_ID",
            "",
        ).strip(),
        youtube_content_owner_id=os.getenv("YOUTUBE_CONTENT_OWNER_ID", "").strip(),
        youtube_use_on_behalf_upload=_parse_bool("YOUTUBE_USE_ON_BEHALF_UPLOAD", False),
        youtube_upload_fallback_to_primary=_parse_bool("YOUTUBE_UPLOAD_FALLBACK_TO_PRIMARY", True),
        youtube_default_privacy=os.getenv("YOUTUBE_DEFAULT_PRIVACY", "private"),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "10"),
        youtube_default_language=os.getenv("YOUTUBE_DEFAULT_LANGUAGE", "en"),
        target_duration_min=int(os.getenv("TARGET_DURATION_MIN", "30")),
        target_width=int(os.getenv("TARGET_WIDTH", "1920")),
        target_height=int(os.getenv("TARGET_HEIGHT", "1080")),
        fps=int(os.getenv("FPS", "30")),
        max_clips_per_run=int(os.getenv("MAX_CLIPS_PER_RUN", "20")),
        min_clip_seconds=int(os.getenv("MIN_CLIP_SECONDS", "5")),
        max_recent_track_lookback=int(os.getenv("MAX_RECENT_TRACK_LOOKBACK", "10")),
        max_recent_clip_lookback=int(os.getenv("MAX_RECENT_CLIP_LOOKBACK", "100")),
        content_tags=tags,
        upload_enabled=_parse_bool("UPLOAD_ENABLED", True),
        publish_at_iso=os.getenv("PUBLISH_AT_ISO", ""),
        assets_tracks_dir=assets_tracks_dir,
        temp_clips_dir=temp_clips_dir,
        temp_renders_dir=temp_renders_dir,
        data_dir=data_dir,
        runs_dir=runs_dir,
        state_db_path=state_db_path,
        database_url=os.getenv("DATABASE_URL", "").strip(),
        pexels_per_page=int(os.getenv("PEXELS_PER_PAGE", "30")),
        pexels_pages_per_tag=int(os.getenv("PEXELS_PAGES_PER_TAG", "2")),
        n8n_webhook_url=os.getenv("N8N_WEBHOOK_URL", "").strip(),
        cleanup_temp_after_run=_parse_bool("CLEANUP_TEMP_AFTER_RUN", True),
        keep_final_output=_parse_bool("KEEP_FINAL_OUTPUT", False),
        render_preset=os.getenv("RENDER_PRESET", "veryfast").strip() or "veryfast",
        render_crf=int(os.getenv("RENDER_CRF", "23")),
        use_local_videos_only=_parse_bool("USE_LOCAL_VIDEOS_ONLY", False),
        local_videos_fallback_to_pexels=_parse_bool("LOCAL_VIDEOS_FALLBACK_TO_PEXELS", True),
        assets_source_videos_dir=assets_source_videos_dir,
        run_mode=run_mode,
        trigger_api_key=os.getenv("TRIGGER_API_KEY", "").strip(),
        no_repeat_clips_in_single_video=_parse_bool("NO_REPEAT_CLIPS_IN_SINGLE_VIDEO", False),
        allow_shorter_unique_video=_parse_bool("ALLOW_SHORTER_UNIQUE_VIDEO", True),
        match_video_duration_to_track=_parse_bool("MATCH_VIDEO_DURATION_TO_TRACK", False),
        tiktok_cuts_enabled=_parse_bool("TIKTOK_CUTS_ENABLED", False),
        tiktok_clips_per_run=max(1, int(os.getenv("TIKTOK_CLIPS_PER_RUN", "3"))),
        tiktok_clip_seconds=max(5, int(os.getenv("TIKTOK_CLIP_SECONDS", "30"))),
        tiktok_width=max(360, int(os.getenv("TIKTOK_WIDTH", "1080"))),
        tiktok_height=max(640, int(os.getenv("TIKTOK_HEIGHT", "1920"))),
        tiktok_output_dir=resolved_tiktok_output_dir,
        telegram_send_tiktok=_parse_bool("TELEGRAM_SEND_TIKTOK", False),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        telegram_api_id=int(os.getenv("TELEGRAM_API_ID", "0").strip() or "0"),
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", "").strip(),
        telegram_session_string=os.getenv("TELEGRAM_SESSION_STRING", "").strip(),
        poyo_api_key=_env_with_fallback("POYO_SEEDANCE_API_KEY", "POYO_API_KEY", ""),
        poyo_api_base_url=_env_with_fallback("POYO_SEEDANCE_API_BASE_URL", "POYO_API_BASE_URL", "https://api.poyo.ai"),
        poyo_generate_path=_env_with_fallback("POYO_SEEDANCE_GENERATE_PATH", "POYO_GENERATE_PATH", "/api/generate/submit"),
        poyo_status_path_template=_env_with_fallback(
            "POYO_SEEDANCE_STATUS_PATH_TEMPLATE",
            "POYO_STATUS_PATH_TEMPLATE",
            "/api/generate/status/{job_id}",
        ),
        poyo_download_url_field=_env_with_fallback(
            "POYO_SEEDANCE_DOWNLOAD_URL_FIELD",
            "POYO_DOWNLOAD_URL_FIELD",
            "data.files.0.file_url",
        ),
        poyo_id_field=_env_with_fallback("POYO_SEEDANCE_ID_FIELD", "POYO_ID_FIELD", "data.task_id"),
        poyo_status_field=_env_with_fallback("POYO_SEEDANCE_STATUS_FIELD", "POYO_STATUS_FIELD", "data.status"),
        poyo_ready_statuses=poyo_ready_statuses,
        poyo_failed_statuses=poyo_failed_statuses,
        poyo_poll_interval_seconds=max(
            1,
            int(_env_with_fallback("POYO_SEEDANCE_POLL_INTERVAL_SECONDS", "POYO_POLL_INTERVAL_SECONDS", "5")),
        ),
        poyo_max_wait_seconds=max(
            10,
            int(_env_with_fallback("POYO_SEEDANCE_MAX_WAIT_SECONDS", "POYO_MAX_WAIT_SECONDS", "600")),
        ),
        video_generation_provider=video_generation_provider,
        minimax_api_key=os.getenv("MINIMAX_API_KEY", "").strip(),
        minimax_api_base_url=os.getenv("MINIMAX_API_BASE_URL", "https://api.minimax.io").strip().rstrip("/")
        or "https://api.minimax.io",
        minimax_video_model=os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-02").strip() or "MiniMax-Hailuo-02",
        minimax_video_duration=max(1, int(os.getenv("MINIMAX_VIDEO_DURATION", "10").strip() or "10")),
        minimax_video_resolution=os.getenv("MINIMAX_VIDEO_RESOLUTION", "768P").strip().upper() or "768P",
        minimax_poll_interval_seconds=max(
            5,
            int(os.getenv("MINIMAX_POLL_INTERVAL_SECONDS", "10").strip() or "10"),
        ),
        minimax_max_wait_seconds=max(
            60,
            int(os.getenv("MINIMAX_MAX_WAIT_SECONDS", "600").strip() or "600"),
        ),
    )
