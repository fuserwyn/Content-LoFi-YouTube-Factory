import requests

from src.fetch_assets import _request_with_retry


class _Resp:
    def __init__(self, payload: dict, ok: bool = True) -> None:
        self.payload = payload
        self.ok = ok

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError("boom")

    def json(self) -> dict:
        return self.payload


def test_request_with_retry_success_after_failure(mocker) -> None:
    calls = [_Resp({}, ok=False), _Resp({"videos": [{"id": 1}]}, ok=True)]
    get_mock = mocker.patch("src.fetch_assets.requests.get", side_effect=calls)
    sleep_mock = mocker.patch("src.fetch_assets.time.sleep")

    payload = _request_with_retry(headers={"Authorization": "x"}, params={"query": "surf"}, max_attempts=3)

    assert payload["videos"][0]["id"] == 1
    assert get_mock.call_count == 2
    sleep_mock.assert_called_once()


def test_request_with_retry_raises_after_max_attempts(mocker) -> None:
    get_mock = mocker.patch("src.fetch_assets.requests.get", side_effect=requests.RequestException("net"))
    sleep_mock = mocker.patch("src.fetch_assets.time.sleep")

    try:
        _request_with_retry(headers={"Authorization": "x"}, params={"query": "surf"}, max_attempts=2)
        raise AssertionError("Expected RequestException")
    except requests.RequestException:
        pass

    assert get_mock.call_count == 2
    sleep_mock.assert_called_once()
