import pytest

from src.bot import (
    BotConfig,
    object_size,
    parse_cadence,
    presigned_upload_url,
    upload_key,
    verify_secret,
)
from src.remote_assets import S3SyncConfig


def _cfg(**overrides) -> BotConfig:
    base = dict(
        token="123:abc",
        database_url="postgresql://x",
        webhook_secret="s3cret",
        public_base_url="https://example.test",
        admin_chat_id="",
        s3=S3SyncConfig(
            enabled=True, bucket="bucket", endpoint_url="https://r2.test",
            region="auto", access_key_id="k", secret_access_key="s",
            videos_prefix="source_videos", tracks_prefix="tracks",
        ),
    )
    base.update(overrides)
    return BotConfig(**base)


def test_configured_requires_token_and_database() -> None:
    assert _cfg().configured is True
    assert _cfg(token="").configured is False
    assert _cfg(database_url="").configured is False


def test_verify_secret_accepts_matching_header() -> None:
    assert verify_secret(_cfg(), "s3cret") is True


def test_verify_secret_rejects_wrong_header() -> None:
    assert verify_secret(_cfg(), "nope") is False


def test_verify_secret_rejects_everything_when_unset() -> None:
    # Незаданный секрет не должен превращаться в «пускать всех»: адрес вебхука
    # угадывается, и тогда кто угодно слал бы боту команды от чужого имени.
    cfg = _cfg(webhook_secret="")

    assert verify_secret(cfg, "") is False
    assert verify_secret(cfg, "anything") is False


def test_upload_key_is_scoped_to_user() -> None:
    key = upload_key(_cfg(), 42, "video.mp4")

    assert key.startswith("uploads/42/")
    assert key.endswith("video.mp4")


def test_upload_key_is_unguessable() -> None:
    # Предсказуемый ключ позволил бы перезаписать чужую загрузку.
    first = upload_key(_cfg(), 42, "video.mp4")
    second = upload_key(_cfg(), 42, "video.mp4")

    assert first != second


def test_upload_key_strips_dangerous_characters() -> None:
    key = upload_key(_cfg(), 7, "../../etc/passwd")

    assert ".." not in key.rsplit("/", 1)[1]


def test_upload_key_falls_back_on_empty_name() -> None:
    key = upload_key(_cfg(), 7, "///")

    assert key.endswith("video.mp4")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("24", 24),
        ("24ч", 24),
        ("раз в 12 часов", 12),
        ("1", 1),
        ("", None),
        ("каждый день", None),
        ("0", None),
        ("1000", None),
    ],
)
def test_parse_cadence(text, expected) -> None:
    assert parse_cadence(text) == expected


def test_presigned_upload_url_signs_a_put(mocker) -> None:
    client = mocker.Mock()
    client.generate_presigned_url.return_value = "https://signed"
    mocker.patch("src.bot.build_s3_client", return_value=client)

    url = presigned_upload_url(_cfg(), "uploads/1/x/video.mp4")

    assert url == "https://signed"
    assert client.generate_presigned_url.call_args[0][0] == "put_object"


def test_object_size_returns_length(mocker) -> None:
    client = mocker.Mock()
    client.head_object.return_value = {"ContentLength": 4096}
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert object_size(_cfg(), "uploads/1/x/video.mp4") == 4096


def test_object_size_is_zero_when_upload_never_landed(mocker) -> None:
    # Иначе воркер взял бы задачу и упал на отсутствующем исходнике.
    client = mocker.Mock()
    client.head_object.side_effect = RuntimeError("404")
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert object_size(_cfg(), "uploads/1/x/missing.mp4") == 0


def test_attach_webhook_skips_when_bot_not_configured() -> None:
    # Лофи-конвейер должен работать в окружении без бота — роут не появляется.
    from fastapi import FastAPI

    from src.bot import attach_webhook

    app = FastAPI()

    assert attach_webhook(app, _cfg(token="")) is False
    assert not [r for r in app.routes if getattr(r, "path", "") == "/telegram/webhook"]


def test_attach_webhook_mounts_route(mocker) -> None:
    from fastapi import FastAPI

    from src.bot import attach_webhook

    mocker.patch("src.bot.build_dispatcher", return_value=mocker.Mock())
    app = FastAPI()

    assert attach_webhook(app, _cfg()) is True
    assert [r for r in app.routes if getattr(r, "path", "") == "/telegram/webhook"]


def test_webhook_rejects_wrong_secret(mocker) -> None:
    # Адрес вебхука угадывается, поэтому подпись — единственная защита.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.bot import attach_webhook

    dispatcher = mocker.Mock()
    mocker.patch("src.bot.build_dispatcher", return_value=dispatcher)
    app = FastAPI()
    attach_webhook(app, _cfg())

    response = TestClient(app).post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )

    assert response.status_code == 403
    dispatcher.feed_update.assert_not_called()


def test_webhook_rejects_missing_secret_header(mocker) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.bot import attach_webhook

    dispatcher = mocker.Mock()
    mocker.patch("src.bot.build_dispatcher", return_value=dispatcher)
    app = FastAPI()
    attach_webhook(app, _cfg())

    response = TestClient(app).post("/telegram/webhook", json={"update_id": 1})

    assert response.status_code == 403
    dispatcher.feed_update.assert_not_called()


def test_upload_token_is_the_random_key_segment() -> None:
    from src.bot import upload_key, upload_token

    key = upload_key(_cfg(), 42, "video.mp4")

    assert upload_token(key) == key.split("/")[2]
    assert len(upload_token(key)) == 32


def test_upload_token_survives_malformed_key() -> None:
    from src.bot import upload_token

    assert upload_token("broken") == ""


def test_delete_object_reports_success(mocker) -> None:
    from src.bot import delete_object

    client = mocker.Mock()
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert delete_object(_cfg(), "uploads/1/x/v.mp4") is True
    assert client.delete_object.call_args.kwargs["Key"] == "uploads/1/x/v.mp4"


def test_delete_object_reports_failure(mocker) -> None:
    # Пометить строку удалённой, соврав про файл, хуже чем признать сбой.
    from src.bot import delete_object

    client = mocker.Mock()
    client.delete_object.side_effect = RuntimeError("denied")
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert delete_object(_cfg(), "uploads/1/x/v.mp4") is False


def test_delete_uses_the_uploads_bucket(mocker) -> None:
    from src.bot import delete_object

    client = mocker.Mock()
    mocker.patch("src.bot.build_s3_client", return_value=client)

    delete_object(_cfg(uploads_bucket="shortscutter"), "k")

    assert client.delete_object.call_args.kwargs["Bucket"] == "shortscutter"


def test_output_prefix_is_scoped_per_source() -> None:
    from src.bot import output_prefix

    assert output_prefix(7, 42) == "outputs/7/42/"


def test_list_outputs_returns_keys_in_order(mocker) -> None:
    from src.bot import list_outputs

    client = mocker.Mock()
    client.list_objects_v2.return_value = {"Contents": [
        {"Key": "outputs/7/42/02_1-15.mp4"},
        {"Key": "outputs/7/42/01_0-10.mp4"},
    ]}
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert list_outputs(_cfg(), 7, 42) == [
        "outputs/7/42/01_0-10.mp4", "outputs/7/42/02_1-15.mp4",
    ]


def test_list_outputs_is_empty_when_nothing_rendered(mocker) -> None:
    from src.bot import list_outputs

    client = mocker.Mock()
    client.list_objects_v2.return_value = {}
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert list_outputs(_cfg(), 7, 42) == []


def test_download_url_is_signed_for_get(mocker) -> None:
    # Ссылка на скачивание должна подписываться под GET: под PUT она
    # открывалась бы в браузере той же ошибкой подписи, что и загрузка.
    from src.bot import presigned_download_url

    client = mocker.Mock()
    client.generate_presigned_url.return_value = "https://signed"
    mocker.patch("src.bot.build_s3_client", return_value=client)

    presigned_download_url(_cfg(), "outputs/7/42/01.mp4")

    assert client.generate_presigned_url.call_args[0][0] == "get_object"


def test_upload_output_reports_failure(mocker) -> None:
    from src.bot import upload_output

    client = mocker.Mock()
    client.upload_file.side_effect = RuntimeError("denied")
    mocker.patch("src.bot.build_s3_client", return_value=client)

    assert upload_output(_cfg(), "/tmp/x.mp4", "outputs/1/1/01.mp4") is False
