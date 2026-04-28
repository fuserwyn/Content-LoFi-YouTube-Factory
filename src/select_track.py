from pathlib import Path
import random


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}


def choose_track(tracks_dir: Path, recently_used_tracks: set[str]) -> Path:
    all_tracks = [
        path
        for path in tracks_dir.glob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not all_tracks:
        raise RuntimeError("No tracks found in assets/tracks")

    preferred = [track for track in all_tracks if str(track) not in recently_used_tracks]
    pool = preferred or all_tracks
    return random.choice(pool)
