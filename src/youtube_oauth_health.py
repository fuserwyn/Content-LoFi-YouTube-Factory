from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig, resolve_youtube_refresh_token
from .youtube_oauth_store import get_stored_refresh_token


@dataclass
class YouTubeTokenProbeResult:
    profile: str
    ok: bool
    message: str
    token_source: str


def probe_youtube_refresh_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> tuple[bool, str]:
    """Exchange refresh token for a short-lived access token (validates refresh is alive)."""
    if not refresh_token.strip():
        return False, "refresh token is empty"

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        return False, f"missing google-auth: {exc}"

    creds = Credentials(
        token=None,
        refresh_token=refresh_token.strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    try:
        creds.refresh(Request())
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    if not creds.token:
        return False, "refresh succeeded but access token is empty"
    return True, "access token refreshed successfully"


def probe_config_profile(config: AppConfig, profile: str | None) -> YouTubeTokenProbeResult:
    normalized = (profile or "default").strip().lower()
    try:
        refresh_token = resolve_youtube_refresh_token(config, profile)
    except ValueError as exc:
        return YouTubeTokenProbeResult(
            profile=normalized,
            ok=False,
            message=str(exc),
            token_source="none",
        )

    stored = get_stored_refresh_token(config.data_dir, profile, path_override=config.youtube_oauth_token_path)
    token_source = "store" if stored and stored == refresh_token else "env"

    ok, message = probe_youtube_refresh_token(
        config.youtube_client_id,
        config.youtube_client_secret,
        refresh_token,
    )
    return YouTubeTokenProbeResult(
        profile=normalized,
        ok=ok,
        message=message,
        token_source=token_source,
    )


def probe_all_profiles(config: AppConfig) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for profile in ("default", "alt"):
        item = probe_config_profile(config, profile)
        if profile == "alt":
            env_alt = (config.youtube_refresh_token_alt or "").strip()
            stored_alt = get_stored_refresh_token(
                config.data_dir, "alt", path_override=config.youtube_oauth_token_path
            )
            if not env_alt and not stored_alt:
                continue
        results.append(
            {
                "profile": item.profile,
                "ok": item.ok,
                "message": item.message,
                "token_source": item.token_source,
            }
        )
    all_ok = all(r["ok"] for r in results) if results else False
    return {"ok": all_ok, "profiles": results}
