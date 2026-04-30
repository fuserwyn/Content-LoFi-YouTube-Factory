from pathlib import Path

import pytest
import requests

from src.notify_telegram import send_files_to_telegram


def test_send_files_to_telegram_noop_when_empty_token(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_post = mocker.patch("src.notify_telegram.requests.post")

    send_files_to_telegram(bot_token="", chat_id="123456", file_paths=[file_path])

    mock_post.assert_not_called()


def test_send_files_to_telegram_noop_when_empty_chat_id(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_post = mocker.patch("src.notify_telegram.requests.post")

    send_files_to_telegram(bot_token="test_token", chat_id="", file_paths=[file_path])

    mock_post.assert_not_called()


def test_send_files_to_telegram_noop_when_empty_files(mocker) -> None:
    mock_post = mocker.patch("src.notify_telegram.requests.post")

    send_files_to_telegram(bot_token="test_token", chat_id="123456", file_paths=[])

    mock_post.assert_not_called()


def test_send_files_to_telegram_posts_each_file(tmp_path: Path, mocker) -> None:
    file1 = tmp_path / "test1.mp4"
    file2 = tmp_path / "test2.mp4"
    file1.write_bytes(b"fake video 1")
    file2.write_bytes(b"fake video 2")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_token",
        chat_id="123456",
        file_paths=[file1, file2],
    )

    assert mock_post.call_count == 2


def test_send_files_to_telegram_includes_caption(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_token",
        chat_id="123456",
        file_paths=[file_path],
        caption_prefix="Test video",
    )

    call_args = mock_post.call_args
    assert call_args[1]["data"]["caption"] == "Test video clip 1/1"


def test_send_files_to_telegram_uses_correct_api_url(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_bot_token",
        chat_id="123456",
        file_paths=[file_path],
    )

    call_args = mock_post.call_args
    url = call_args[0][0]
    assert url == "https://api.telegram.org/bottest_bot_token/sendDocument"


def test_send_files_to_telegram_sends_as_document(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_token",
        chat_id="123456",
        file_paths=[file_path],
    )

    call_args = mock_post.call_args
    files = call_args[1]["files"]
    assert "document" in files
    assert files["document"][0] == "test.mp4"
    assert files["document"][2] == "video/mp4"


def test_send_files_to_telegram_raises_on_http_error(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock(side_effect=requests.HTTPError("401 Unauthorized"))
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    with pytest.raises(requests.HTTPError):
        send_files_to_telegram(
            bot_token="invalid_token",
            chat_id="123456",
            file_paths=[file_path],
        )


def test_send_files_to_telegram_handles_timeout(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mocker.patch(
        "src.notify_telegram.requests.post",
        side_effect=requests.Timeout("Request timeout"),
    )

    with pytest.raises(requests.Timeout):
        send_files_to_telegram(
            bot_token="test_token",
            chat_id="123456",
            file_paths=[file_path],
        )


def test_send_files_to_telegram_uses_correct_timeout(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_token",
        chat_id="123456",
        file_paths=[file_path],
    )

    call_args = mock_post.call_args
    assert call_args[1]["timeout"] == 120


def test_send_files_to_telegram_formats_multiple_captions(tmp_path: Path, mocker) -> None:
    file1 = tmp_path / "test1.mp4"
    file2 = tmp_path / "test2.mp4"
    file3 = tmp_path / "test3.mp4"
    file1.write_bytes(b"fake video 1")
    file2.write_bytes(b"fake video 2")
    file3.write_bytes(b"fake video 3")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_token",
        chat_id="123456",
        file_paths=[file1, file2, file3],
        caption_prefix="TikTok",
    )

    assert mock_post.call_count == 3
    # Check captions
    call1_caption = mock_post.call_args_list[0][1]["data"]["caption"]
    call2_caption = mock_post.call_args_list[1][1]["data"]["caption"]
    call3_caption = mock_post.call_args_list[2][1]["data"]["caption"]

    assert call1_caption == "TikTok clip 1/3"
    assert call2_caption == "TikTok clip 2/3"
    assert call3_caption == "TikTok clip 3/3"


def test_send_files_to_telegram_includes_chat_id_in_data(tmp_path: Path, mocker) -> None:
    file_path = tmp_path / "test.mp4"
    file_path.write_bytes(b"fake video")

    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_post = mocker.patch("src.notify_telegram.requests.post", return_value=mock_response)

    send_files_to_telegram(
        bot_token="test_token",
        chat_id="987654321",
        file_paths=[file_path],
    )

    call_args = mock_post.call_args
    assert call_args[1]["data"]["chat_id"] == "987654321"
