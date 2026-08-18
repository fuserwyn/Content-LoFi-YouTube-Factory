from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.remote_assets import S3SyncConfig
from src.bot import BotConfig
from src.upload_page import attach_upload_page


def _cfg(**overrides) -> BotConfig:
    base = dict(
        token="123:abc", database_url="postgresql://x", webhook_secret="s",
        public_base_url="https://example.test", admin_chat_id="",
        s3=S3SyncConfig(
            enabled=True, bucket="b", endpoint_url="", region="auto",
            access_key_id="k", secret_access_key="s",
            videos_prefix="v", tracks_prefix="t",
        ),
    )
    base.update(overrides)
    return BotConfig(**base)


def _client(mocker, *, key="uploads/1/" + "a" * 32 + "/video.mp4"):
    mocker.patch("src.upload_page.find_storage_key", return_value=key)
    mocker.patch("src.upload_page.storage_problem", return_value="")
    mocker.patch("src.upload_page.presigned_upload_url", return_value="https://signed.test/put")
    app = FastAPI()
    attach_upload_page(app, _cfg())
    return TestClient(app)


def test_page_renders_with_the_presigned_url(mocker) -> None:
    response = _client(mocker).get("/upload/" + "a" * 32)

    assert response.status_code == 200
    assert "https://signed.test/put" in response.text
    assert "PUT" in response.text


def test_page_rejects_malformed_token(mocker) -> None:
    # Короткий или нешестнадцатеричный токен даже не ищем в базе.
    client = _client(mocker)

    assert client.get("/upload/short").status_code == 404
    assert client.get("/upload/" + "z" * 32).status_code == 404


def test_page_404s_for_unknown_token(mocker) -> None:
    mocker.patch("src.upload_page.find_storage_key", return_value="")
    mocker.patch("src.upload_page.storage_problem", return_value="")
    mocker.patch("src.upload_page.presigned_upload_url", return_value="x")
    app = FastAPI()
    attach_upload_page(app, _cfg())

    assert TestClient(app).get("/upload/" + "b" * 32).status_code == 404


def test_page_not_mounted_without_bot_config() -> None:
    app = FastAPI()

    assert attach_upload_page(app, _cfg(token="")) is False
    assert not [r for r in app.routes if "/upload/" in getattr(r, "path", "")]


def test_page_reports_missing_bucket_instead_of_form(mocker) -> None:
    # Иначе юзер заливает гигабайты в стену и видит только «обрыв сети».
    mocker.patch("src.upload_page.find_storage_key", return_value="uploads/1/x/v.mp4")
    mocker.patch("src.upload_page.storage_problem", return_value="Хранилище не найдено.")
    app = FastAPI()
    attach_upload_page(app, _cfg())

    response = TestClient(app).get("/upload/" + "a" * 32)

    assert response.status_code == 503
    assert "Хранилище не найдено." in response.text
    assert "XMLHttpRequest" not in response.text


def test_storage_problem_flags_absent_bucket(mocker) -> None:
    from src.upload_page import storage_problem

    client = mocker.Mock()
    client.head_bucket.side_effect = RuntimeError("404")
    mocker.patch("src.upload_page.build_s3_client", return_value=client)

    assert "не найдено" in storage_problem(_cfg())


def test_storage_problem_flags_missing_cors(mocker) -> None:
    client = mocker.Mock()
    client.get_bucket_cors.side_effect = RuntimeError("no cors")
    mocker.patch("src.upload_page.build_s3_client", return_value=client)
    from src.upload_page import storage_problem

    assert "CORS" in storage_problem(_cfg())


def test_storage_problem_flags_cors_without_put(mocker) -> None:
    client = mocker.Mock()
    client.get_bucket_cors.return_value = {"CORSRules": [{"AllowedMethods": ["GET"]}]}
    mocker.patch("src.upload_page.build_s3_client", return_value=client)
    from src.upload_page import storage_problem

    assert "не разрешают загрузку" in storage_problem(_cfg())


def test_storage_problem_silent_when_ready(mocker) -> None:
    client = mocker.Mock()
    client.get_bucket_cors.return_value = {"CORSRules": [{"AllowedMethods": ["PUT", "GET"]}]}
    mocker.patch("src.upload_page.build_s3_client", return_value=client)
    from src.upload_page import storage_problem

    assert storage_problem(_cfg()) == ""
