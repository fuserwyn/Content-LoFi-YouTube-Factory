"""Dispatch video generation to PoYo-compatible API or direct MiniMax (Hailuo)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AppConfig
from .minimax_video import generate_and_download_minimax_video, generate_stitched_minimax_videos
from .poyo_video import generate_and_download_poyo_video, generate_stitched_poyo_videos


def generate_external_video(
    config: AppConfig,
    poyo_payload: dict,
    output_path: Path,
    segment_count: int,
) -> dict[str, Any]:
    provider = config.video_generation_provider
    if provider == "minimax":
        if not config.minimax_api_key.strip():
            raise RuntimeError("VIDEO_GENERATION_PROVIDER=minimax but MINIMAX_API_KEY is empty")
        if segment_count <= 1:
            return generate_and_download_minimax_video(
                api_key=config.minimax_api_key,
                base_url=config.minimax_api_base_url,
                payload=poyo_payload,
                output_path=output_path,
                default_model=config.minimax_video_model,
                default_duration=config.minimax_video_duration,
                default_resolution=config.minimax_video_resolution,
                poll_interval_seconds=config.minimax_poll_interval_seconds,
                max_wait_seconds=config.minimax_max_wait_seconds,
            )
        return generate_stitched_minimax_videos(
            api_key=config.minimax_api_key,
            base_url=config.minimax_api_base_url,
            base_payload=poyo_payload,
            segment_count=segment_count,
            output_path=output_path,
            default_model=config.minimax_video_model,
            default_duration=config.minimax_video_duration,
            default_resolution=config.minimax_video_resolution,
            poll_interval_seconds=config.minimax_poll_interval_seconds,
            max_wait_seconds=config.minimax_max_wait_seconds,
        )

    if provider != "poyo":
        raise RuntimeError(f"Unknown VIDEO_GENERATION_PROVIDER: {provider!r} (use 'poyo' or 'minimax')")

    if segment_count <= 1:
        return generate_and_download_poyo_video(
            api_key=config.poyo_api_key,
            base_url=config.poyo_api_base_url,
            generate_path=config.poyo_generate_path,
            status_path_template=config.poyo_status_path_template,
            payload=poyo_payload,
            output_path=output_path,
            id_field=config.poyo_id_field,
            status_field=config.poyo_status_field,
            download_url_field=config.poyo_download_url_field,
            ready_statuses=config.poyo_ready_statuses,
            failed_statuses=config.poyo_failed_statuses,
            poll_interval_seconds=config.poyo_poll_interval_seconds,
            max_wait_seconds=config.poyo_max_wait_seconds,
        )
    return generate_stitched_poyo_videos(
        api_key=config.poyo_api_key,
        base_url=config.poyo_api_base_url,
        generate_path=config.poyo_generate_path,
        status_path_template=config.poyo_status_path_template,
        base_payload=poyo_payload,
        segment_count=segment_count,
        output_path=output_path,
        id_field=config.poyo_id_field,
        status_field=config.poyo_status_field,
        download_url_field=config.poyo_download_url_field,
        ready_statuses=config.poyo_ready_statuses,
        failed_statuses=config.poyo_failed_statuses,
        poll_interval_seconds=config.poyo_poll_interval_seconds,
        max_wait_seconds=config.poyo_max_wait_seconds,
    )
