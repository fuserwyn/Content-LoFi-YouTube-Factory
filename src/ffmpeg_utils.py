"""Shared ffmpeg invocation helpers that cap CPU so video encoding does not
starve the web server (uvicorn) running in the same Railway process.

Two levers, both controllable via env:
- ``nice`` lowers the OS scheduling priority of ffmpeg so the higher-priority
  web server preempts it and ``/health`` stays responsive even at 100% CPU
  (this is what stops Railway from killing the instance mid-render).
- output-side ``-threads`` caps how many cores libx264 grabs.
"""

from __future__ import annotations

import os
import shutil


def _render_threads() -> int:
    """Encoder thread cap. ``RENDER_THREADS=0`` (default) means cpu_count-1.

    On Railway set RENDER_THREADS to your vCPU allocation minus one (e.g. 1).
    """
    raw = os.getenv("RENDER_THREADS", "0").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n > 0:
        return n
    cores = os.cpu_count() or 1
    return max(1, cores - 1)


def _render_nice() -> int | None:
    """Niceness applied to ffmpeg. ``RENDER_NICE<=0`` disables the nice prefix."""
    raw = os.getenv("RENDER_NICE", "10").strip()
    try:
        level = int(raw)
    except ValueError:
        level = 10
    return level if level > 0 else None


def _nice_prefix() -> list[str]:
    level = _render_nice()
    if level is not None and shutil.which("nice"):
        return ["nice", "-n", str(level)]
    return []


def finalize_ffmpeg_command(command: list[str]) -> list[str]:
    """Add CPU-yielding prefix + output-side ``-threads`` to an ffmpeg command.

    ``command`` must start with ``"ffmpeg"`` and end with the output path
    (``-threads`` is injected as an output option, i.e. right before the last
    token, so it caps the encoder rather than the demuxer).
    """
    if not command or command[0] != "ffmpeg":
        return command
    out = list(command)
    out[-1:-1] = ["-threads", str(_render_threads())]
    return [*_nice_prefix(), *out]
