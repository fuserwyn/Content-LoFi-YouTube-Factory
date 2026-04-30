from pathlib import Path

import pytest

from src.generate_meta import VideoMeta
from src.upload_youtube import UploadResult, upload_video


def _setup_youtube_mocks(mocker):
    """Helper to set up all YouTube API mocks."""
    mock_creds_instance = mocker.Mock()
    mock_credentials_class = mocker.patch("google.oauth2.credentials.Credentials", return_value=mock_creds_instance)
    
    mock_build = mocker.patch("googleapiclient.discovery.build")
    mock_youtube = mocker.Mock()
    mock_build.return_value = mock_youtube

    mock_videos = mocker.Mock()
    mock_insert = mocker.Mock()
    mock_execute = mocker.Mock(return_value={"id": "test_video_id"})
    mock_insert.execute = mock_execute
    mock_videos.insert.return_value = mock_insert
    mock_youtube.videos.return_value = mock_videos

    mock_media_upload = mocker.patch("googleapiclient.http.MediaFileUpload")

    return {
        "credentials_class": mock_credentials_class,
        "credentials_instance": mock_creds_instance,
        "build": mock_build,
        "youtube": mock_youtube,
        "videos": mock_videos,
        "insert": mock_insert,
        "execute": mock_execute,
        "media_upload": mock_media_upload,
    }


def test_upload_video_creates_credentials(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(
        title="Test Video",
        description="Test description",
        tags=["test", "video"],
    )

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Verify Credentials was called with correct parameters
    mocks["credentials_class"].assert_called_once()
    call_kwargs = mocks["credentials_class"].call_args[1]
    assert call_kwargs["refresh_token"] == "test_refresh_token"
    assert call_kwargs["client_id"] == "test_client_id"
    assert call_kwargs["client_secret"] == "test_client_secret"
    assert "https://www.googleapis.com/auth/youtube.upload" in call_kwargs["scopes"]


def test_upload_video_builds_youtube_client(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(
        title="Test Video",
        description="Test description",
        tags=["test"],
    )

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    mocks["build"].assert_called_once_with("youtube", "v3", credentials=mocks["credentials_instance"])


def test_upload_video_constructs_metadata(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(
        title="My Test Video",
        description="This is a test description",
        tags=["tag1", "tag2", "tag3"],
    )

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        category_id="22",
        default_language="ru",
    )

    # Check the body passed to insert
    call_kwargs = mocks["videos"].insert.call_args[1]
    body = call_kwargs["body"]

    assert body["snippet"]["title"] == "My Test Video"
    assert body["snippet"]["description"] == "This is a test description"
    assert body["snippet"]["tags"] == ["tag1", "tag2", "tag3"]
    assert body["snippet"]["categoryId"] == "22"
    assert body["snippet"]["defaultLanguage"] == "ru"


def test_upload_video_sets_privacy_status(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        default_privacy="unlisted",
    )

    call_kwargs = mocks["videos"].insert.call_args[1]
    body = call_kwargs["body"]
    assert body["status"]["privacyStatus"] == "unlisted"


def test_upload_video_sets_publish_at_for_private(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        default_privacy="private",
        publish_at_iso="2026-05-01T12:00:00Z",
    )

    call_kwargs = mocks["videos"].insert.call_args[1]
    body = call_kwargs["body"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-05-01T12:00:00Z"


def test_upload_video_does_not_set_publish_at_for_public(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        default_privacy="public",
        publish_at_iso="2026-05-01T12:00:00Z",
    )

    call_kwargs = mocks["videos"].insert.call_args[1]
    body = call_kwargs["body"]
    assert body["status"]["privacyStatus"] == "public"
    assert "publishAt" not in body["status"]


def test_upload_video_uses_correct_category(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        category_id="15",  # Pets & Animals
    )

    call_kwargs = mocks["videos"].insert.call_args[1]
    body = call_kwargs["body"]
    assert body["snippet"]["categoryId"] == "15"


def test_upload_video_uses_correct_language(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        default_language="fr",
    )

    call_kwargs = mocks["videos"].insert.call_args[1]
    body = call_kwargs["body"]
    assert body["snippet"]["defaultLanguage"] == "fr"


def test_upload_video_returns_video_id(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)
    mocks["execute"].return_value = {"id": "abc123xyz"}

    result = upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    assert isinstance(result, UploadResult)
    assert result.video_id == "abc123xyz"
    assert result.status == "private"


def test_upload_video_handles_upload_error(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)
    mocks["insert"].execute.side_effect = Exception("Upload failed")

    with pytest.raises(Exception, match="Upload failed"):
        upload_video(
            video_path=video_path,
            meta=meta,
            client_id="test_client_id",
            client_secret="test_client_secret",
            refresh_token="test_refresh_token",
        )


def test_upload_video_uses_media_file_upload(tmp_path: Path, mocker) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video")

    meta = VideoMeta(title="Test", description="Test", tags=["test"])

    mocks = _setup_youtube_mocks(mocker)

    upload_video(
        video_path=video_path,
        meta=meta,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Verify MediaFileUpload was called with correct parameters
    mocks["media_upload"].assert_called_once_with(str(video_path), chunksize=-1, resumable=True)
