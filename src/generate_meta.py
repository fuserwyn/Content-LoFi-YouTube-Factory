from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import random


@dataclass
class VideoMeta:
    title: str
    description: str
    tags: list[str]


def generate_metadata(track_path: Path, tags_seed: list[str]) -> VideoMeta:
    mood_words = ["focus", "calm", "study", "night vibes", "deep work", "rainy flow"]
    pick = random.choice(mood_words)
    track_name = track_path.stem.replace("_", " ").strip()

    title = f"Lo-Fi Surf & Nature Mix | {pick} | {track_name}"
    tags = list(dict.fromkeys(["lofi", "chill beats", "study music", "nature", "surf"] + tags_seed))[:15]

    generated_at = datetime.now(timezone.utc).isoformat()
    description = (
        f"Track: {track_name}\n"
        "Visuals: Licensed stock footage (nature/surf).\n"
        f"Generated at: {generated_at}\n\n"
        "#lofi #chill #surf #nature #study"
    )

    return VideoMeta(title=title[:100], description=description[:5000], tags=tags)
