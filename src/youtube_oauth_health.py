from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig, resolve_youtube_refresh_token
from .youtube_oauth_store import get_stored_refresh_token

# A refresh grant may only ask for scopes the token actually carries; extras cause Google
# invalid_scope. OAuth start requests upload + readonly (see youtube_oauth_web.py), but tokens
# issued before that carry upload only — and asking for upload alone downscopes the access
# token, which makes channels.list(mine=true) fail with insufficientPermissions. So try both
# scopes first and fall back to upload-only for legacy tokens.
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
_REFRESH_SCOPE_ATTEMPTS = (
    [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE],
    [YOUTUBE_UPLOAD_SCOPE],
)


@dataclass
class YouTubeTokenProbeResult:
    profile: str
    ok: bool
    message: str
    token_source: str
    channel_id: str = ""
    channel_title: str = ""
    channel_custom_url: str = ""


def _fetch_mine_channel(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> tuple[bool, str, dict[str, str]]:
    """Refresh access token and resolve the YouTube channel that will receive uploads."""
    if not refresh_token.strip():
        return False, "refresh token is empty", {}

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        return False, f"missing google deps: {exc}", {}

    creds = None
    last_error: Exception | None = None
    for scopes in _REFRESH_SCOPE_ATTEMPTS:
        candidate = Credentials(
            token=None,
            refresh_token=refresh_token.strip(),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=list(scopes),
        )
        try:
            candidate.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        creds = candidate
        break

    if creds is None:
        return False, str(last_error), {}

    if not creds.token:
        return False, "refresh succeeded but access token is empty", {}

    try:
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        response = youtube.channels().list(part="snippet", mine=True).execute()
    except Exception as exc:  # noqa: BLE001
        return (
            True,
            f"access token ok; channel lookup failed (re-auth may be needed for channel name): {exc}",
            {},
        )

    items = response.get("items") or []
    if not items:
        return True, "access token ok; no YouTube channel on this Google account", {}

    channel = items[0]
    snippet = channel.get("snippet") or {}
    info = {
        "channel_id": str(channel.get("id") or ""),
        "channel_title": str(snippet.get("title") or ""),
        "channel_custom_url": str(snippet.get("customUrl") or ""),
    }
    title = info["channel_title"] or info["channel_id"] or "unknown"
    return True, f"uploads go to channel: {title}", info


def probe_youtube_refresh_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> tuple[bool, str]:
    """Exchange refresh token for a short-lived access token (validates refresh is alive)."""
    ok, message, _info = _fetch_mine_channel(client_id, client_secret, refresh_token)
    return ok, message


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

    ok, message, info = _fetch_mine_channel(
        config.youtube_client_id,
        config.youtube_client_secret,
        refresh_token,
    )
    return YouTubeTokenProbeResult(
        profile=normalized,
        ok=ok,
        message=message,
        token_source=token_source,
        channel_id=info.get("channel_id", ""),
        channel_title=info.get("channel_title", ""),
        channel_custom_url=info.get("channel_custom_url", ""),
    )


def _profile_dict(item: YouTubeTokenProbeResult) -> dict[str, Any]:
    return {
        "profile": item.profile,
        "ok": item.ok,
        "message": item.message,
        "token_source": item.token_source,
        "channel_id": item.channel_id,
        "channel_title": item.channel_title,
        "channel_custom_url": item.channel_custom_url,
        "channel_url": (
            f"https://www.youtube.com/channel/{item.channel_id}" if item.channel_id else ""
        ),
    }


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
        results.append(_profile_dict(item))
    all_ok = all(r["ok"] for r in results) if results else False
    return {"ok": all_ok, "profiles": results}
