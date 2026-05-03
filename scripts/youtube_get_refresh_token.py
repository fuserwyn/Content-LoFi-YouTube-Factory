#!/usr/bin/env python3
"""
One-shot OAuth: print YOUTUBE_REFRESH_TOKEN for Content Factory.

Uses the same scope as upload: youtube.upload.

Prerequisites:
  - Google Cloud: YouTube Data API v3 enabled.
  - OAuth client: **Desktop app** (easiest), or **Web application** with an extra
    redirect URI (see below).
  - Put YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (factory root)
    or export them in the shell.

If you use **Web application** OAuth client, open Google Cloud → Credentials →
your client → *Authorized redirect URIs* and add **exactly** (including slash):
  http://localhost:8080/
If port 8080 is busy, set YOUTUBE_OAUTH_LOCAL_PORT=8090 and add that URI instead
(e.g. http://localhost:8090/).

Run (from factory root):
  pip install google-auth-oauthlib python-dotenv
  python scripts/youtube_get_refresh_token.py

Log in in the browser as the Google account that should own uploads
(second channel → that account). Copy the printed line into your .env as
``YOUTUBE_REFRESH_TOKEN`` for the default channel, or ``YOUTUBE_REFRESH_TOKEN_ALT``
if this token is for the alternate channel (use ``youtube_oauth_profile`` / ``alt`` in API calls).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    factory_root = Path(__file__).resolve().parent.parent
    load_dotenv(factory_root / ".env")
    load_dotenv()

    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(
            "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET. "
            "Set them in .env or the environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Install: pip install google-auth-oauthlib",
            file=sys.stderr,
        )
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    env_port = os.environ.get("YOUTUBE_OAUTH_LOCAL_PORT", "").strip()
    ports = (
        [int(env_port)]
        if env_port.isdigit()
        else [8080, 8090, 8765, 9000]
    )

    creds = None
    last_oserr: OSError | None = None
    for port in ports:
        try:
            print(
                f"OAuth redirect (must match Google Cloud if Web client): "
                f"http://localhost:{port}/",
                file=sys.stderr,
            )
            # Fixed port so redirect_uri matches Google Cloud (not random port=0).
            creds = flow.run_local_server(
                port=port,
                access_type="offline",
                prompt="consent",
                open_browser=True,
            )
            break
        except OSError as exc:
            # macOS: [Errno 48] Address already in use
            last_oserr = exc
            if getattr(exc, "errno", None) in (48, 98, 10048):  # EADDRINUSE
                continue
            raise

    if creds is None:
        print(
            f"Could not bind a local port (tried {ports}): {last_oserr}\n"
            "Free one of these ports or set YOUTUBE_OAUTH_LOCAL_PORT.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not creds.refresh_token:
        print(
            "No refresh_token in response. Revoke app access at "
            "https://myaccount.google.com/permissions and run again, "
            "or create a new **Desktop** OAuth client.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nAdd or replace in your .env:\n")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}\n")


if __name__ == "__main__":
    main()
