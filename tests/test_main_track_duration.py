from pathlib import Path

from src.main import _probe_audio_duration_seconds


class _Proc:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_probe_audio_duration_seconds_parses_value(mocker) -> None:
    mocker.patch("src.main.subprocess.run", return_value=_Proc(0, "183.7\n"))
    value = _probe_audio_duration_seconds(Path("/tmp/fake.mp3"))
    assert value == 183


def test_probe_audio_duration_seconds_returns_none_on_error(mocker) -> None:
    mocker.patch("src.main.subprocess.run", return_value=_Proc(1, ""))
    value = _probe_audio_duration_seconds(Path("/tmp/fake.mp3"))
    assert value is None
