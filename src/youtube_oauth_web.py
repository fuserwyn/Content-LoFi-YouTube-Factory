from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


@dataclass
class PendingOAuth:
    flow: Any
    profile: str
    created_at: float


def build_web_client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def create_authorization_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> Any:
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        build_web_client_config(client_id, client_secret, redirect_uri),
        scopes=[YOUTUBE_UPLOAD_SCOPE],
        redirect_uri=redirect_uri,
    )


def start_authorization(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    profile: str,
) -> tuple[str, str, PendingOAuth]:
    flow = create_authorization_flow(client_id, client_secret, redirect_uri)
    state = secrets.token_urlsafe(24)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    pending = PendingOAuth(flow=flow, profile=profile, created_at=time.time())
    return auth_url, state, pending


def complete_authorization(pending: PendingOAuth, authorization_response: str) -> str:
    pending.flow.fetch_token(authorization_response=authorization_response)
    creds = pending.flow.credentials
    if not creds or not creds.refresh_token:
        raise RuntimeError(
            "Google did not return refresh_token. Revoke app at "
            "https://myaccount.google.com/permissions and retry with prompt=consent."
        )
    return str(creds.refresh_token)
