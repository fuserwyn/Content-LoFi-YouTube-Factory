from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .generate_meta import VideoMeta

logger = logging.getLogger(__name__)


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
    content_owner_id: str = "",
    *,
    use_on_behalf_upload: bool = False,
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

    # onBehalfOfContentOwner + onBehalfOfContentOwnerChannel are for YouTube CMS / content
    # partners only. Passing only the channel id causes:
    # ERROR_CONTENT_OWNER_CHANNEL_WITHOUT_CONTENT_OWNER
    upload_channel = channel_id.strip() if channel_id else ""
    owner = content_owner_id.strip() if content_owner_id else ""
    if upload_channel and not owner:
        logger.warning(
            "youtube_upload: YOUTUBE_UPLOAD_CHANNEL_ID is set without YOUTUBE_CONTENT_OWNER_ID; "
            "skipping onBehalfOf* (partner-only). Upload goes to the channel for this OAuth token. "
            "For a brand channel without CMS: obtain refresh_token while Google asks which "
            "channel to use, or leave YOUTUBE_UPLOAD_CHANNEL_ID empty."
        )

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
    if owner and upload_channel and use_on_behalf_upload:
        insert_kwargs["onBehalfOfContentOwner"] = owner
        insert_kwargs["onBehalfOfContentOwnerChannel"] = upload_channel
    elif owner and upload_channel and not use_on_behalf_upload:
        logger.debug(
            "youtube_upload: onBehalfOf* skipped (use_on_behalf_upload=false); "
            "video goes to the channel linked to the OAuth refresh token."
        )

    request = youtube.videos().insert(**insert_kwargs)
    response = request.execute()
    return UploadResult(video_id=response["id"], status=status["privacyStatus"])
