from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_DEFAULT_PROFILE = "default"
_ALT_PROFILE = "alt"
_VALID_PROFILES = {_DEFAULT_PROFILE, _ALT_PROFILE}


def _normalize_profile(profile: str | None) -> str:
    raw = (profile or "").strip().lower()
    if raw in {"", "default", "primary", "main", "1"}:
        return _DEFAULT_PROFILE
    if raw in {"alt", "secondary", "second", "2", "channel2", "other"}:
        return _ALT_PROFILE
    raise ValueError(f"Invalid youtube_oauth_profile {profile!r}; use 'default' or 'alt'")


def token_store_path(data_dir: Path, override: str = "") -> Path:
    if override.strip():
        return Path(override.strip())
    return data_dir / "youtube_oauth_tokens.json"


def load_token_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"profiles": {}}
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        return {"profiles": {}}
    if "profiles" not in payload or not isinstance(payload["profiles"], dict):
        payload["profiles"] = {}
    return payload


def save_refresh_token(path: Path, profile: str, refresh_token: str) -> None:
    key = _normalize_profile(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_token_store(path)
    payload["profiles"][key] = {
        "refresh_token": refresh_token.strip(),
        "updated_at": int(time.time()),
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=True, indent=2)


def get_stored_refresh_token(data_dir: Path, profile: str | None, *, path_override: str = "") -> str:
    path = token_store_path(data_dir, path_override)
    if not path.exists():
        return ""
    payload = load_token_store(path)
    key = _normalize_profile(profile)
    entry = payload["profiles"].get(key) or {}
    token = entry.get("refresh_token") if isinstance(entry, dict) else ""
    return str(token).strip() if token else ""


def oauth_status(data_dir: Path, *, path_override: str = "") -> dict[str, Any]:
    path = token_store_path(data_dir, path_override)
    payload = load_token_store(path)
    profiles: dict[str, Any] = {}
    for key in (_DEFAULT_PROFILE, _ALT_PROFILE):
        entry = payload["profiles"].get(key) or {}
        token = ""
        updated_at = 0
        if isinstance(entry, dict):
            token = str(entry.get("refresh_token", "")).strip()
            updated_at = int(entry.get("updated_at", 0) or 0)
        profiles[key] = {
            "has_token": bool(token),
            "updated_at": updated_at,
            "token_suffix": token[-6:] if len(token) >= 6 else "",
        }
    return {"store_path": str(path), "profiles": profiles}
