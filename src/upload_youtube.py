from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .generate_meta import VideoMeta


@dataclass
class UploadResult:
    video_id: str
    status: str


def upload_video(
    video_path: Path,
    meta: VideoMeta,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    default_privacy: str = "private",
    category_id: str = "10",
    default_language: str = "en",
    publish_at_iso: str = "",
    channel_id: str = "",
) -> UploadResult:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    youtube = build("youtube", "v3", credentials=creds)

    # Target channel when the Google account has several channels (e.g. brand / UC… id).
    # YouTube Data API: onBehalfOfContentOwnerChannel; OAuth user must manage this channel.
    upload_channel = channel_id.strip() if channel_id else ""

    status: dict[str, str | bool] = {"privacyStatus": default_privacy}
    if default_privacy == "private" and publish_at_iso:
        status["publishAt"] = publish_at_iso

    body = {
        "snippet": {
            "title": meta.title,
            "description": meta.description,
            "tags": meta.tags,
            "categoryId": category_id,
            "defaultLanguage": default_language,
        },
        "status": status,
    }

    insert_kwargs: dict[str, object] = {
        "part": "snippet,status",
        "body": body,
        "media_body": MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    }
    if upload_channel:
        insert_kwargs["onBehalfOfContentOwnerChannel"] = upload_channel

    request = youtube.videos().insert(**insert_kwargs)
    response = request.execute()
    return UploadResult(video_id=response["id"], status=status["privacyStatus"])
