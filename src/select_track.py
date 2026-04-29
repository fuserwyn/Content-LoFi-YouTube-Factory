from pathlib import Path
import random
import logging


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}

LOGGER = logging.getLogger("content_factory")


def choose_track(
    tracks_dir: Path,
    recently_used_tracks: set[str],
    preferred_track: str | None = None,
    allow_recent_preferred: bool = False,
) -> Path:
    all_tracks = [
        path
        for path in tracks_dir.glob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not all_tracks:
        raise RuntimeError("No tracks found in assets/tracks")

    preferred_path: Path | None = None
    if preferred_track:
        candidate = Path(preferred_track)
        preferred_path = candidate if candidate.is_absolute() else (tracks_dir / candidate)
        if not preferred_path.exists() or not preferred_path.is_file():
            LOGGER.info("TRACK_SELECT: preferred_track not found: %s", preferred_track)
            preferred_path = None

    if preferred_path is not None:
        pref_str = str(preferred_path)
        if allow_recent_preferred or pref_str not in recently_used_tracks:
            LOGGER.info("TRACK_SELECT: choosing preferred track: %s", preferred_path)
            return preferred_path
        LOGGER.info("TRACK_SELECT: preferred track is recent; falling back. %s", preferred_path)

    preferred = [track for track in all_tracks if str(track) not in recently_used_tracks]
    pool = preferred or all_tracks
    LOGGER.info(
        "TRACK_SELECT: tracks_dir=%s total=%d preferred=%d recent_lookback=%d",
        tracks_dir,
        len(all_tracks),
        len(preferred),
        len(recently_used_tracks),
    )
    if recently_used_tracks:
        sample_recent = list(recently_used_tracks)[:5]
        LOGGER.info("TRACK_SELECT: recent sample=%s", sample_recent)

    LOGGER.info(
        "TRACK_SELECT: pool=%s selected_preview=%s",
        "preferred" if preferred else "all_tracks",
        pool[0].name if pool else "n/a",
    )
    return random.choice(pool)
