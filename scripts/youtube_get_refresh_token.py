#!/usr/bin/env python3
"""
One-shot OAuth: print YOUTUBE_REFRESH_TOKEN for Content Factory.

Uses the same scope as upload: youtube.upload.

Prerequisites:
  - Google Cloud: YouTube Data API v3 enabled.
  - OAuth client: **Desktop app** (easiest), or **Web application** with redirect URI
    ``http://localhost:8080/`` (see below).
  - Put YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (factory root).

Run (from factory root):
  pip install google-auth-oauthlib python-dotenv
  python3 scripts/youtube_get_refresh_token.py

Optional: YOUTUBE_OAUTH_CLIENT_TYPE=desktop if your Google client is Desktop app (default: web).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _explain_missing_code(redirect_uri: str) -> None:
    print(
        "\nGoogle redirect did not include ?code= (MissingCodeError).\n"
        "Common fixes:\n"
        "  1. Complete login in the browser — do not close the tab early.\n"
        "  2. Check the address bar after redirect — if you see error=access_denied, "
        "allow access or add your Google account under Audience → Test users (Testing only).\n"
        "  3. In Google Cloud → Clients → your OAuth client, Authorized redirect URIs "
        f"must include exactly:\n     {redirect_uri}\n"
        "  4. For local script, create a **Desktop app** OAuth client and set "
        "YOUTUBE_OAUTH_CLIENT_TYPE=desktop in .env.\n"
        "  5. Revoke old access: https://myaccount.google.com/permissions → run script again.\n",
        file=sys.stderr,
    )


def _run_web_flow(client_id: str, client_secret: str, port: int):
    # InstalledAppFlow provides run_local_server; plain Flow does not.
    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        from oauthlib.oauth2.rfc6749.errors import MissingCodeError
    except ImportError:
        MissingCodeError = Exception  # type: ignore[misc, assignment]

    redirect_uri = f"http://localhost:{port}/"
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    flow.oauth2session.redirect_uri = redirect_uri
    print(f"OAuth redirect (add in Google Cloud if missing): {redirect_uri}", file=sys.stderr)
    print("Opening browser for Google login…", file=sys.stderr, flush=True)
    try:
        return flow.run_local_server(
            port=port,
            access_type="offline",
            prompt="consent",
            open_browser=True,
            authorization_prompt_message=(
                "Browser should open. Log in and allow access. "
                "If nothing opens, check the terminal for a URL or use Railway /youtube/oauth/start."
            ),
            success_message="Authorization complete. Return to the terminal.",
        )
    except MissingCodeError:
        _explain_missing_code(redirect_uri)
        raise


def _run_desktop_flow(client_id: str, client_secret: str, port: int):
    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        from oauthlib.oauth2.rfc6749.errors import MissingCodeError
    except ImportError:
        MissingCodeError = Exception  # type: ignore[misc, assignment]

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }
    redirect_uri = f"http://localhost:{port}/"
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    flow.oauth2session.redirect_uri = redirect_uri
    print(f"OAuth redirect (Desktop client): {redirect_uri}", file=sys.stderr)
    try:
        return flow.run_local_server(
            port=port,
            access_type="offline",
            prompt="consent",
            open_browser=True,
        )
    except MissingCodeError:
        _explain_missing_code(redirect_uri)
        raise


def main() -> None:
    factory_root = Path(__file__).resolve().parent.parent
    load_dotenv(factory_root / ".env")
    load_dotenv()

    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    client_type = os.environ.get("YOUTUBE_OAUTH_CLIENT_TYPE", "web").strip().lower()
    if not client_id or not client_secret:
        print(
            "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        print("Install: pip install google-auth-oauthlib", file=sys.stderr)
        sys.exit(1)

    env_port = os.environ.get("YOUTUBE_OAUTH_LOCAL_PORT", "").strip()
    ports = [int(env_port)] if env_port.isdigit() else [8080, 8090, 8765, 9000]

    creds = None
    last_oserr: OSError | None = None
    last_exc: Exception | None = None
    run_flow = _run_desktop_flow if client_type == "desktop" else _run_web_flow

    for port in ports:
        try:
            creds = run_flow(client_id, client_secret, port)
            break
        except OSError as exc:
            last_oserr = exc
            if getattr(exc, "errno", None) in (48, 98, 10048):
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break

    if creds is None:
        if last_exc is not None:
            raise last_exc
        print(
            f"Could not bind a local port (tried {ports}): {last_oserr}\n"
            "Set YOUTUBE_OAUTH_LOCAL_PORT or free a port.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not creds.refresh_token:
        print(
            "No refresh_token returned. Revoke app at https://myaccount.google.com/permissions "
            "and run again (prompt=consent).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nAdd or replace in Railway / .env:\n")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}\n")


if __name__ == "__main__":
    main()
