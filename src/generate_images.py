from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
from urllib.parse import quote

import requests


@dataclass
class GeneratedImage:
    scene_index: int
    prompt: str
    local_path: Path


def generate_lora_style_images(
    tags: list[str],
    output_dir: Path,
    target_duration_seconds: int,
    scene_seconds: int,
    style_suffix: str,
) -> list[GeneratedImage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_count = max(1, (target_duration_seconds + max(1, scene_seconds) - 1) // max(1, scene_seconds))

    prompts = _build_scene_prompts(tags=tags, scene_count=scene_count, style_suffix=style_suffix)
    generated: list[GeneratedImage] = []
    for idx, prompt in enumerate(prompts):
        seed = random.randint(1, 1_000_000_000)
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            f"?width=1920&height=1080&seed={seed}&nologo=true&enhance=true"
        )
        image_path = output_dir / f"scene_{idx:03d}.jpg"
        _download_image(url, image_path)
        generated.append(GeneratedImage(scene_index=idx, prompt=prompt, local_path=image_path))
    return generated


def _build_scene_prompts(tags: list[str], scene_count: int, style_suffix: str) -> list[str]:
    palette = [
        "golden sunset over calm water",
        "misty pine forest at dawn",
        "rainy window with city bokeh lights",
        "mountain lake with gentle fog",
        "moonlit beach with soft waves",
        "cozy cabin in light snowfall",
        "cherry blossoms in spring breeze",
        "quiet meadow with fireflies at dusk",
        "autumn forest trail with warm tones",
        "night sky with stars above hills",
    ]
    base = ", ".join(tags) if tags else "nature"
    prompts: list[str] = []
    for i in range(scene_count):
        topic = palette[i % len(palette)]
        prompts.append(f"{base}, {topic}, {style_suffix}")
    return prompts


def _download_image(url: str, destination: Path) -> None:
    with requests.get(url, timeout=90, stream=True) as response:
        response.raise_for_status()
        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
