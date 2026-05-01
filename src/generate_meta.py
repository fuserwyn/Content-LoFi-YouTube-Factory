from dataclasses import dataclass
from pathlib import Path
import random


@dataclass
class VideoMeta:
    title: str
    description: str
    tags: list[str]


def generate_metadata(track_path: Path, tags_seed: list[str], theme: str | None = None) -> VideoMeta:
    mood_words = ["focus", "calm", "study", "night vibes", "deep work", "rainy flow"]
    pick = theme.strip() if theme and theme.strip() else random.choice(mood_words)
    track_name = track_path.stem.replace("_", " ").strip()

    title = f"Lo-Fi Surf & Nature Mix | {pick} | {track_name}"
    tags = list(dict.fromkeys(["lofi", "chill beats", "study music", "nature", "surf"] + tags_seed))[:15]

    description = f"Track: {track_name}\n\n#lofi #chill #surf #nature #study"

    return VideoMeta(title=title[:100], description=description[:5000], tags=tags)
