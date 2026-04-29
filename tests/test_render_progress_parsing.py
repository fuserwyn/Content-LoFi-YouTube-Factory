from src.render_video import _extract_ffmpeg_time_seconds, _hhmmss_to_seconds


def test_hhmmss_to_seconds_parses_fractional() -> None:
    assert _hhmmss_to_seconds("00:01:30.50") == 90.5


def test_extract_ffmpeg_time_seconds_reads_line() -> None:
    line = "frame=  544 fps=31 q=-1.0 size=   1024kB time=00:00:22.20 bitrate= 377.9kbits/s speed=1.25x"
    seconds = _extract_ffmpeg_time_seconds(line)
    assert seconds == 22.2


def test_extract_ffmpeg_time_seconds_returns_none_without_time() -> None:
    assert _extract_ffmpeg_time_seconds("random log line") is None
