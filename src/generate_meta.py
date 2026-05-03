from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoMeta:
    title: str
    description: str
    tags: list[str]


def _track_display_name(track_path: Path) -> str:
    return track_path.stem.replace("_", " ").strip()


def _theme_public_label(theme: str | None) -> str | None:
    """Strip subtitle after middle dot (e.g. 'Lake Sunrise · Quiet Canvas' -> 'Lake Sunrise')."""
    if not theme or not theme.strip():
        return None
    t = theme.strip()
    sep = "\u00b7"  # ·
    if sep in t:
        t = t.split(sep, 1)[0].strip()
    return t or None


def _visuals_slug(tags_seed: list[str], theme: str | None) -> str:
    parts: list[str] = []
    if theme and theme.strip():
        head = theme.strip().lower().replace("/", " ").split()
        if head:
            tok = "".join(c for c in head[0] if c.isalnum())
            if tok:
                parts.append(tok[:24])
    for raw in tags_seed:
        w = raw.strip().lower().replace(",", "").split()
        if not w:
            continue
        tok = "".join(c for c in w[0] if c.isalnum())
        if tok and tok not in parts:
            parts.append(tok[:24])
    if not parts:
        parts = ["nature", "surf"]
    return "/".join(parts[:5])


def _hashtag_line(tags_seed: list[str]) -> str:
    seed_tokens: list[str] = []
    for raw in tags_seed:
        w = raw.strip().lower().lstrip("#").replace(",", "")
        if not w:
            continue
        tok = "".join(c for c in w.split()[0] if c.isalnum())
        if tok and tok not in seed_tokens:
            seed_tokens.append(tok)

    line: list[str] = []
    for needle in ("lofi", "chill"):
        line.append(f"#{needle}")
    for tok in seed_tokens:
        tag = f"#{tok}"
        if tag not in line:
            line.append(tag)
    for needle in ("surf", "nature", "study"):
        t = f"#{needle}"
        if t not in line:
            line.append(t)
    return " ".join(line[:15])


def _youtube_tags(tags_seed: list[str], theme: str | None) -> list[str]:
    out: list[str] = []
    if theme and theme.strip():
        out.append(theme.strip()[:40])
    for t in tags_seed:
        s = t.strip()
        if s and s not in out:
            out.append(s[:40])
    for extra in ("lofi", "chill", "ambient", "study"):
        if extra not in [x.lower() for x in out]:
            out.append(extra)
    dedup: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup[:15]


def generate_metadata(track_path: Path, tags_seed: list[str], theme: str | None = None) -> VideoMeta:
    track_name = _track_display_name(track_path)
    label = _theme_public_label(theme)
    headline = label if label else "Lo-Fi"

    title = f"{headline} | {track_name}"[:100]

    visuals = _visuals_slug(tags_seed, label)
    description = (
        f"Track: {track_name}\n"
        f"Visuals: Licensed stock footage ({visuals}).\n\n"
        f"{_hashtag_line(tags_seed)}"
    )[:5000]

    tags = _youtube_tags(tags_seed, label)

    return VideoMeta(title=title, description=description, tags=tags)
