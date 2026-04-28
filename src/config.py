from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass
class AppConfig:
    pexels_api_key: str
    youtube_client_id: str
    youtube_client_secret: str
    youtube_refresh_token: str
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


def _require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing required env var: {name}")
    return value


def _parse_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def load_config() -> AppConfig:
    load_dotenv()

    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"
    runs_dir = data_dir / "runs"
    assets_tracks_dir = project_root / "assets" / "tracks"
    temp_clips_dir = project_root / "temp" / "clips"
    temp_renders_dir = project_root / "temp" / "renders"
    state_db_path = data_dir / "state.db"

    for path in [data_dir, runs_dir, assets_tracks_dir, temp_clips_dir, temp_renders_dir]:
        path.mkdir(parents=True, exist_ok=True)

    tags_raw = os.getenv("CONTENT_TAGS", "nature,surf,ocean,sunset")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    return AppConfig(
        pexels_api_key=_require_env("PEXELS_API_KEY"),
        youtube_client_id=_require_env("YOUTUBE_CLIENT_ID"),
        youtube_client_secret=_require_env("YOUTUBE_CLIENT_SECRET"),
        youtube_refresh_token=_require_env("YOUTUBE_REFRESH_TOKEN"),
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
    )
