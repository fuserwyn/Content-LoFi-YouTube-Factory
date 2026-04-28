import pytest

from src.notify_n8n import send_run_notification


class _OkResponse:
    def raise_for_status(self) -> None:
        return None


def test_send_run_notification_noop_when_empty_url() -> None:
    send_run_notification("", {"status": "success"})


def test_send_run_notification_posts_payload(mocker) -> None:
    post_mock = mocker.patch("src.notify_n8n.requests.post", return_value=_OkResponse())
    payload = {"run_id": "x1", "status": "success"}
    send_run_notification("https://example.com/webhook", payload)
    post_mock.assert_called_once_with("https://example.com/webhook", json=payload, timeout=20)
