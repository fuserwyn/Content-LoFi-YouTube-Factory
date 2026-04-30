import random
from pathlib import Path

import pytest
import requests

from src.generate_images import (
    GeneratedImage,
    _build_scene_prompts,
    _download_image,
    generate_lora_style_images,
)


def test_build_scene_prompts_creates_correct_count() -> None:
    prompts = _build_scene_prompts(tags=["nature"], scene_count=5, style_suffix="anime style")
    assert len(prompts) == 5


def test_build_scene_prompts_cycles_through_palette() -> None:
    prompts = _build_scene_prompts(tags=["nature"], scene_count=12, style_suffix="anime style")
    assert len(prompts) == 12
    # With 10 palette items, item 0 and item 10 should use the same palette entry
    assert "golden sunset" in prompts[0]
    assert "golden sunset" in prompts[10]


def test_build_scene_prompts_includes_tags() -> None:
    prompts = _build_scene_prompts(tags=["ocean", "waves"], scene_count=3, style_suffix="anime style")
    for prompt in prompts:
        assert "ocean" in prompt
        assert "waves" in prompt


def test_build_scene_prompts_includes_style_suffix() -> None:
    prompts = _build_scene_prompts(tags=["nature"], scene_count=3, style_suffix="cyberpunk style")
    for prompt in prompts:
        assert "cyberpunk style" in prompt


def test_build_scene_prompts_uses_default_base_when_no_tags() -> None:
    prompts = _build_scene_prompts(tags=[], scene_count=2, style_suffix="anime style")
    for prompt in prompts:
        assert "nature" in prompt


def test_generate_lora_style_images_creates_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "images"
    assert not output_dir.exists()

    # Mock the download to avoid actual HTTP calls
    def mock_download(url: str, destination: Path) -> None:
        destination.write_bytes(b"fake image data")

    import src.generate_images
    original_download = src.generate_images._download_image
    src.generate_images._download_image = mock_download

    try:
        random.seed(42)
        generate_lora_style_images(
            tags=["test"],
            output_dir=output_dir,
            target_duration_seconds=10,
            scene_seconds=5,
            style_suffix="test style",
        )
        assert output_dir.exists()
        assert output_dir.is_dir()
    finally:
        src.generate_images._download_image = original_download


def test_generate_lora_style_images_downloads_all_scenes(tmp_path: Path) -> None:
    output_dir = tmp_path / "images"

    # Mock the download
    def mock_download(url: str, destination: Path) -> None:
        destination.write_bytes(b"fake image data")

    import src.generate_images
    original_download = src.generate_images._download_image
    src.generate_images._download_image = mock_download

    try:
        random.seed(42)
        result = generate_lora_style_images(
            tags=["test"],
            output_dir=output_dir,
            target_duration_seconds=15,
            scene_seconds=5,
            style_suffix="test style",
        )
        # 15 seconds / 5 seconds per scene = 3 scenes
        assert len(result) == 3
        assert all(isinstance(img, GeneratedImage) for img in result)
        assert all(img.local_path.exists() for img in result)
    finally:
        src.generate_images._download_image = original_download


def test_download_image_saves_file(tmp_path: Path, mocker) -> None:
    destination = tmp_path / "test_image.jpg"
    fake_content = b"fake image content"

    # Mock requests.get
    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock()
    mock_response.iter_content = mocker.Mock(return_value=[fake_content])
    mock_response.__enter__ = mocker.Mock(return_value=mock_response)
    mock_response.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("src.generate_images.requests.get", return_value=mock_response)

    _download_image("https://example.com/image.jpg", destination)

    assert destination.exists()
    assert destination.read_bytes() == fake_content


def test_download_image_handles_http_error(tmp_path: Path, mocker) -> None:
    destination = tmp_path / "test_image.jpg"

    # Mock requests.get to raise HTTP error
    mock_response = mocker.Mock()
    mock_response.raise_for_status = mocker.Mock(side_effect=requests.HTTPError("404 Not Found"))
    mock_response.__enter__ = mocker.Mock(return_value=mock_response)
    mock_response.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("src.generate_images.requests.get", return_value=mock_response)

    with pytest.raises(requests.HTTPError):
        _download_image("https://example.com/image.jpg", destination)


def test_download_image_handles_network_error(tmp_path: Path, mocker) -> None:
    destination = tmp_path / "test_image.jpg"

    # Mock requests.get to raise connection error
    mocker.patch(
        "src.generate_images.requests.get",
        side_effect=requests.ConnectionError("Network error"),
    )

    with pytest.raises(requests.ConnectionError):
        _download_image("https://example.com/image.jpg", destination)


def test_generate_lora_style_images_uses_random_seeds(tmp_path: Path) -> None:
    output_dir = tmp_path / "images"
    generated_urls = []

    # Mock the download to capture URLs
    def mock_download(url: str, destination: Path) -> None:
        generated_urls.append(url)
        destination.write_bytes(b"fake image data")

    import src.generate_images
    original_download = src.generate_images._download_image
    src.generate_images._download_image = mock_download

    try:
        random.seed(42)
        generate_lora_style_images(
            tags=["test"],
            output_dir=output_dir,
            target_duration_seconds=10,
            scene_seconds=5,
            style_suffix="test style",
        )

        # Check that URLs contain seed parameter
        assert len(generated_urls) == 2
        for url in generated_urls:
            assert "seed=" in url
            assert "nologo=true" in url
            assert "enhance=true" in url
    finally:
        src.generate_images._download_image = original_download


def test_generate_lora_style_images_returns_correct_structure(tmp_path: Path) -> None:
    output_dir = tmp_path / "images"

    # Mock the download
    def mock_download(url: str, destination: Path) -> None:
        destination.write_bytes(b"fake image data")

    import src.generate_images
    original_download = src.generate_images._download_image
    src.generate_images._download_image = mock_download

    try:
        random.seed(42)
        result = generate_lora_style_images(
            tags=["ocean"],
            output_dir=output_dir,
            target_duration_seconds=10,
            scene_seconds=5,
            style_suffix="anime style",
        )

        assert len(result) == 2
        for idx, img in enumerate(result):
            assert img.scene_index == idx
            assert isinstance(img.prompt, str)
            assert "ocean" in img.prompt
            assert "anime style" in img.prompt
            assert img.local_path.name == f"scene_{idx:03d}.jpg"
    finally:
        src.generate_images._download_image = original_download
