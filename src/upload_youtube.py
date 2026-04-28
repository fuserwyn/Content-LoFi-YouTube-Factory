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

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )
    response = request.execute()
    return UploadResult(video_id=response["id"], status=status["privacyStatus"])
