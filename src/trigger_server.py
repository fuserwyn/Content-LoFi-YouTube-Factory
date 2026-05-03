from __future__ import annotations

import copy
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from .config import AppConfig, resolve_youtube_refresh_token
from .generate_meta import VideoMeta, generate_metadata
from .logger import setup_logger
from .main import PexelsRenderBundle, _cleanup_temp_files, render_pexels_track_bundle, run as pipeline_run
from .state_store import RunRecord, create_state_store
from .notify_telegram import send_message_to_telegram
from .video_generation import generate_external_video
from .select_track import SUPPORTED_EXTENSIONS
from .tiktok_cuts import create_tiktok_cuts
from .upload_youtube import upload_video
from .n8n_short_queue import ack_publish, peek_next_job, persist_queue_after_render


class RunRequest(BaseModel):
    track: str | None = None
    allow_recent_preferred: bool = False
    tags: list[str] | None = None
    theme: str | None = None


class TikTokCutsRequest(BaseModel):
    source_video_path: str
    clips_count: int | None = None
    clip_seconds: int | None = None
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    tracks_dir: str | None = None
    output_dir: str | None = None


class PublishVideoWithShortsRequest(BaseModel):
    source_video_path: str
    skip_if_source_missing: bool = False
    track_for_metadata: str | None = None
    theme: str | None = None
    tags: list[str] | None = None
    publish_at_iso: str | None = None
    shorts_count: int = 3
    short_delay_hours: int = 1
    short_interval_hours: int = 7
    main_privacy_status: str = "public"
    shorts_privacy_status: str = "public"
    cleanup_source_after_publish: bool = True
    cleanup_shorts_after_upload: bool = True
    clip_seconds: int | None = None
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    tracks_dir: str | None = None
    output_dir: str | None = None
    short_publish_offset_hours: list[float] | None = None
    shorts_use_main_track_thirds: bool = False
    youtube_oauth_profile: str | None = Field(
        default=None,
        description="default | alt — second channel uses YOUTUBE_REFRESH_TOKEN_ALT",
    )


class GeneratePoyoAndPublishRequest(BaseModel):
    poyo_payload: dict
    output_filename: str | None = None
    track_for_metadata: str | None = None
    theme: str | None = None
    tags: list[str] | None = None
    publish_at_iso: str | None = None
    shorts_count: int = 3
    short_delay_hours: int = 24
    short_interval_hours: int = 24
    main_privacy_status: str = "public"
    shorts_privacy_status: str = "public"
    cleanup_source_after_publish: bool = True
    cleanup_shorts_after_upload: bool = True
    clip_seconds: int | None = None
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    tracks_dir: str | None = None
    output_dir: str | None = None
    poyo_stitch_segments: int = Field(default=1, ge=1, le=4)
    youtube_oauth_profile: str | None = Field(
        default=None,
        description="default | alt — second channel uses YOUTUBE_REFRESH_TOKEN_ALT",
    )


class GeneratePoyoShortsOnlyRequest(BaseModel):
    poyo_payload: dict
    output_filename: str | None = None
    track_for_metadata: str | None = None
    theme: str | None = None
    tags: list[str] | None = None
    publish_at_iso: str | None = None
    shorts_count: int = 3
    short_delay_hours: int = 24
    short_interval_hours: int = 24
    shorts_privacy_status: str = "public"
    cleanup_source_after_publish: bool = True
    cleanup_shorts_after_upload: bool = True
    clip_seconds: int | None = None
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    tracks_dir: str | None = None
    output_dir: str | None = None
    poyo_stitch_segments: int = Field(default=1, ge=1, le=4)
    youtube_oauth_profile: str | None = Field(
        default=None,
        description="default | alt — second channel uses YOUTUBE_REFRESH_TOKEN_ALT",
    )


class WorkflowPublishShortRequest(BaseModel):
    """Один шорт на диске → загрузка на YouTube (оркестрация через n8n)."""

    short_path: str
    main_title: str
    description: str
    tags: list[str]
    short_index: int = 0
    shorts_privacy_status: str = "public"
    cleanup_after: bool = True
    publish_at_iso: str | None = None
    youtube_oauth_profile: str | None = Field(
        default=None,
        description="default | alt — second channel uses YOUTUBE_REFRESH_TOKEN_ALT",
    )


class RunPublishWithShortsRequest(BaseModel):
    """Pexels/local clips + track render, then main upload + scheduled shorts."""

    track: str | None = None
    allow_recent_preferred: bool = False
    tags: list[str] | None = None
    theme: str | None = None
    publish_at_iso: str | None = None
    shorts_count: int = 3
    short_delay_hours: int = 24
    short_interval_hours: int = 48
    short_publish_offset_hours: list[float] | None = Field(default_factory=lambda: [12.0, 24.0, 36.0])
    shorts_use_main_track_thirds: bool = True
    main_privacy_status: str = "public"
    shorts_privacy_status: str = "public"
    cleanup_source_after_publish: bool = True
    cleanup_shorts_after_upload: bool = True
    clip_seconds: int | None = 30
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    tracks_dir: str | None = None
    output_dir: str | None = None
    youtube_oauth_profile: str | None = Field(
        default=None,
        description="default | alt — second channel uses YOUTUBE_REFRESH_TOKEN_ALT",
    )


def _publish_video_request_from_bundle_run(
    bundle: PexelsRenderBundle,
    req: RunPublishWithShortsRequest,
) -> PublishVideoWithShortsRequest:
    return PublishVideoWithShortsRequest(
        source_video_path=str(bundle.render_result.output_path),
        skip_if_source_missing=False,
        track_for_metadata=str(bundle.selected_track),
        theme=req.theme,
        tags=req.tags,
        publish_at_iso=req.publish_at_iso,
        shorts_count=req.shorts_count,
        short_delay_hours=req.short_delay_hours,
        short_interval_hours=req.short_interval_hours,
        short_publish_offset_hours=req.short_publish_offset_hours,
        shorts_use_main_track_thirds=req.shorts_use_main_track_thirds,
        main_privacy_status=req.main_privacy_status,
        shorts_privacy_status=req.shorts_privacy_status,
        cleanup_source_after_publish=req.cleanup_source_after_publish,
        cleanup_shorts_after_upload=req.cleanup_shorts_after_upload,
        clip_seconds=req.clip_seconds,
        clip_min_seconds=req.clip_min_seconds,
        clip_max_seconds=req.clip_max_seconds,
        tracks_dir=req.tracks_dir,
        output_dir=req.output_dir,
        youtube_oauth_profile=req.youtube_oauth_profile,
    )


def publish_main_and_shorts_impl(
    *,
    config: AppConfig,
    logger: Any,
    payload: PublishVideoWithShortsRequest,
) -> dict:
    source_video_path = _resolve_source_video_path(payload.source_video_path, config)
    if not source_video_path.exists():
        if payload.skip_if_source_missing:
            return {
                "status": "skipped",
                "message": "source video missing, skipped by policy",
                "source_video_path": str(source_video_path),
            }
        raise RuntimeError(f"source video not found: {source_video_path}")
    tracks_dir = _resolve_tracks_dir(payload.tracks_dir, config)
    output_dir = _resolve_path(payload.output_dir, config.tiktok_output_dir)
    shorts_count = max(1, payload.shorts_count)
    clip_seconds = config.tiktok_clip_seconds if payload.clip_seconds is None else payload.clip_seconds

    publish_base = _parse_publish_datetime(payload.publish_at_iso)
    logger.info(
        "TRIGGER: publish-video-with-shorts requested | source=%s publish_at=%s shorts_count=%s short_delay_hours=%s short_interval_hours=%s",
        source_video_path,
        publish_base.isoformat(),
        shorts_count,
        payload.short_delay_hours,
        payload.short_interval_hours,
    )

    try:
        yt_refresh = resolve_youtube_refresh_token(config, payload.youtube_oauth_profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tags_seed = payload.tags or config.content_tags
    track_for_meta = payload.track_for_metadata
    if track_for_meta:
        track_path = _resolve_source_video_path(track_for_meta, config)
    else:
        track_path = source_video_path
    main_meta = generate_metadata(track_path, tags_seed, theme=payload.theme)
    main_upload = upload_video(
        video_path=source_video_path,
        meta=main_meta,
        client_id=config.youtube_client_id,
        client_secret=config.youtube_client_secret,
        refresh_token=yt_refresh,
        default_privacy=payload.main_privacy_status,
        category_id=config.youtube_category_id,
        default_language=config.youtube_default_language,
        publish_at_iso=(
            publish_base.isoformat().replace("+00:00", "Z")
            if payload.main_privacy_status == "private"
            else ""
        ),
        channel_id=config.youtube_upload_channel_id,
        content_owner_id=config.youtube_content_owner_id,
        use_on_behalf_upload=config.youtube_use_on_behalf_upload,
        primary_refresh_token=config.youtube_refresh_token,
        fallback_to_primary_on_error=config.youtube_upload_fallback_to_primary,
    )

    offsets_raw = payload.short_publish_offset_hours
    if offsets_raw is not None and len(offsets_raw) == shorts_count:
        short_hour_offsets = [float(h) for h in offsets_raw]
    else:
        short_hour_offsets = [
            float(payload.short_delay_hours + payload.short_interval_hours * i) for i in range(shorts_count)
        ]

    fixed_track_audio: Path | None = None
    slice_track_parts = False
    if payload.shorts_use_main_track_thirds:
        if not track_for_meta:
            raise RuntimeError("shorts_use_main_track_thirds requires track_for_metadata")
        fixed_track_audio = track_path
        slice_track_parts = True

    shorts = create_tiktok_cuts(
        source_video_path=source_video_path,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=shorts_count,
        clip_seconds=max(5, clip_seconds),
        width=config.tiktok_width,
        height=config.tiktok_height,
        fps=config.fps,
        encode_preset=config.render_preset,
        crf=config.render_crf,
        clip_min_seconds=max(5, payload.clip_min_seconds) if payload.clip_min_seconds is not None else None,
        clip_max_seconds=max(5, payload.clip_max_seconds) if payload.clip_max_seconds is not None else None,
        fixed_track_for_audio=fixed_track_audio,
        slice_track_into_equal_parts=slice_track_parts,
    )

    short_uploads: list[dict] = []
    for index, short in enumerate(shorts):
        short_publish_at = publish_base + timedelta(hours=short_hour_offsets[index])
        short_meta = VideoMeta(
            title=f"{main_meta.title[:88]} · Short {index + 1}",
            description=main_meta.description,
            tags=list(dict.fromkeys(main_meta.tags + ["shorts"]))[:15],
        )
        short_upload = upload_video(
            video_path=short.output_path,
            meta=short_meta,
            client_id=config.youtube_client_id,
            client_secret=config.youtube_client_secret,
            refresh_token=yt_refresh,
            default_privacy=payload.shorts_privacy_status,
            category_id=config.youtube_category_id,
            default_language=config.youtube_default_language,
            publish_at_iso=(
                short_publish_at.isoformat().replace("+00:00", "Z")
                if payload.shorts_privacy_status == "private"
                else ""
            ),
            channel_id=config.youtube_upload_channel_id,
            content_owner_id=config.youtube_content_owner_id,
            use_on_behalf_upload=config.youtube_use_on_behalf_upload,
            primary_refresh_token=config.youtube_refresh_token,
            fallback_to_primary_on_error=config.youtube_upload_fallback_to_primary,
        )
        short_uploads.append(
            {
                "video_id": short_upload.video_id,
                "status": short_upload.status,
                "path": str(short.output_path),
                "publish_at_iso": short_publish_at.isoformat().replace("+00:00", "Z"),
                "start_second": short.start_second,
                "duration_second": short.duration_second,
            }
        )

    if config.telegram_bot_token and config.telegram_chat_id:
        youtube_url = f"https://www.youtube.com/watch?v={main_upload.video_id}"
        send_message_to_telegram(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            message=youtube_url,
        )
        if short_uploads:
            short_lines = "\n".join(
                f"https://www.youtube.com/shorts/{su['video_id']}" for su in short_uploads
            )
            send_message_to_telegram(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
                message=short_lines,
            )

    if payload.cleanup_shorts_after_upload:
        for short in shorts:
            short.output_path.unlink(missing_ok=True)

    if payload.cleanup_source_after_publish:
        source_video_path.unlink(missing_ok=True)

    return {
        "status": "ok",
        "message": "main video and shorts uploaded",
        "main_video": {
            "video_id": main_upload.video_id,
            "status": main_upload.status,
            "path": str(source_video_path),
            "publish_at_iso": publish_base.isoformat().replace("+00:00", "Z"),
        },
        "shorts_count": len(short_uploads),
        "shorts": short_uploads,
        "schedule": {
            "short_publish_offset_hours": short_hour_offsets,
            "short_delay_hours": payload.short_delay_hours,
            "short_interval_hours": payload.short_interval_hours,
        },
    }


def workflow_render_main_and_cut_shorts_impl(
    *,
    config: AppConfig,
    logger: Any,
    bundle: PexelsRenderBundle,
    payload: RunPublishWithShortsRequest,
) -> dict[str, Any]:
    """Рендер уже сделан: залить только long, нарезать шорты на диск, без загрузки шортов (n8n шлёт /workflow/publish-short)."""
    source_video_path = bundle.render_result.output_path
    tracks_dir = _resolve_tracks_dir(payload.tracks_dir, config)
    output_dir = _resolve_path(payload.output_dir, config.tiktok_output_dir)
    shorts_count = max(1, payload.shorts_count)
    clip_seconds = config.tiktok_clip_seconds if payload.clip_seconds is None else payload.clip_seconds
    publish_base = _parse_publish_datetime(payload.publish_at_iso)
    tags_seed = payload.tags or config.content_tags
    track_path_meta = bundle.selected_track
    main_meta = generate_metadata(track_path_meta, tags_seed, theme=payload.theme)
    logger.info(
        "WORKFLOW: render-main-and-shorts | out=%s track=%s shorts_count=%s",
        source_video_path,
        track_path_meta,
        shorts_count,
    )
    try:
        yt_refresh = resolve_youtube_refresh_token(config, payload.youtube_oauth_profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    main_upload = upload_video(
        video_path=source_video_path,
        meta=main_meta,
        client_id=config.youtube_client_id,
        client_secret=config.youtube_client_secret,
        refresh_token=yt_refresh,
        default_privacy=payload.main_privacy_status,
        category_id=config.youtube_category_id,
        default_language=config.youtube_default_language,
        publish_at_iso=(
            publish_base.isoformat().replace("+00:00", "Z")
            if payload.main_privacy_status == "private"
            else ""
        ),
        channel_id=config.youtube_upload_channel_id,
        content_owner_id=config.youtube_content_owner_id,
        use_on_behalf_upload=config.youtube_use_on_behalf_upload,
        primary_refresh_token=config.youtube_refresh_token,
        fallback_to_primary_on_error=config.youtube_upload_fallback_to_primary,
    )
    fixed_track_audio: Path | None = None
    slice_track_parts = False
    if payload.shorts_use_main_track_thirds:
        fixed_track_audio = track_path_meta
        slice_track_parts = True

    shorts = create_tiktok_cuts(
        source_video_path=source_video_path,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        clips_count=shorts_count,
        clip_seconds=max(5, clip_seconds),
        width=config.tiktok_width,
        height=config.tiktok_height,
        fps=config.fps,
        encode_preset=config.render_preset,
        crf=config.render_crf,
        clip_min_seconds=max(5, payload.clip_min_seconds) if payload.clip_min_seconds is not None else None,
        clip_max_seconds=max(5, payload.clip_max_seconds) if payload.clip_max_seconds is not None else None,
        fixed_track_for_audio=fixed_track_audio,
        slice_track_into_equal_parts=slice_track_parts,
    )
    shorts_files: list[dict[str, Any]] = []
    for idx, short in enumerate(shorts):
        shorts_files.append(
            {
                "index": idx,
                "path": str(short.output_path.resolve()),
                "start_second": short.start_second,
                "duration_second": short.duration_second,
            }
        )

    if config.telegram_bot_token and config.telegram_chat_id:
        youtube_url = f"https://www.youtube.com/watch?v={main_upload.video_id}"
        send_message_to_telegram(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            message=youtube_url,
        )

    if payload.cleanup_source_after_publish:
        source_video_path.unlink(missing_ok=True)

    return {
        "status": "ok",
        "message": "main uploaded; short files created (upload via /workflow/publish-short from n8n)",
        "main_video": {
            "video_id": main_upload.video_id,
            "status": main_upload.status,
            "path": str(source_video_path) if source_video_path.exists() else "",
        },
        "selected_track": str(bundle.selected_track),
        "main_meta": {
            "title": main_meta.title,
            "description": main_meta.description,
            "tags": list(main_meta.tags),
        },
        "shorts_files": shorts_files,
        "shorts_privacy_status": payload.shorts_privacy_status,
        "cleanup_shorts_after_upload": payload.cleanup_shorts_after_upload,
    }


def workflow_publish_short_impl(
    *,
    config: AppConfig,
    logger: Any,
    payload: WorkflowPublishShortRequest,
) -> dict[str, Any]:
    short_path = Path(payload.short_path)
    if not short_path.is_file():
        raise RuntimeError(f"short file not found: {short_path}")
    try:
        yt_refresh = resolve_youtube_refresh_token(config, payload.youtube_oauth_profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    meta = VideoMeta(
        title=f"{payload.main_title[:88]} · Short {payload.short_index + 1}",
        description=payload.description,
        tags=list(dict.fromkeys([*payload.tags, "shorts"]))[:15],
    )
    publish_at = ""
    if payload.shorts_privacy_status.strip().lower() == "private" and payload.publish_at_iso:
        publish_at = payload.publish_at_iso.replace("+00:00", "Z")
    upload_result = upload_video(
        video_path=short_path,
        meta=meta,
        client_id=config.youtube_client_id,
        client_secret=config.youtube_client_secret,
        refresh_token=yt_refresh,
        default_privacy=payload.shorts_privacy_status,
        category_id=config.youtube_category_id,
        default_language=config.youtube_default_language,
        publish_at_iso=publish_at,
        channel_id=config.youtube_upload_channel_id,
        content_owner_id=config.youtube_content_owner_id,
        use_on_behalf_upload=config.youtube_use_on_behalf_upload,
        primary_refresh_token=config.youtube_refresh_token,
        fallback_to_primary_on_error=config.youtube_upload_fallback_to_primary,
    )
    if config.telegram_bot_token and config.telegram_chat_id:
        send_message_to_telegram(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            message=f"https://www.youtube.com/shorts/{upload_result.video_id}",
        )
    if payload.cleanup_after:
        short_path.unlink(missing_ok=True)
    logger.info(
        "WORKFLOW: publish-short index=%s video_id=%s path=%s",
        payload.short_index + 1,
        upload_result.video_id,
        short_path,
    )
    return {
        "status": "ok",
        "video_id": upload_result.video_id,
        "youtube_short_url": f"https://www.youtube.com/shorts/{upload_result.video_id}",
    }


def _prepare_shorts_only_vertical_single_clip(poyo_payload: dict) -> dict:
    """One PoYo generation job, vertical 9:16 hints for common video models (shorts pipeline)."""
    out = copy.deepcopy(poyo_payload)
    inp = out.get("input")
    if not isinstance(inp, dict):
        inp = {}
    top_prompt = out.get("prompt")
    if isinstance(top_prompt, str) and top_prompt.strip() and not str(inp.get("prompt", "")).strip():
        inp["prompt"] = top_prompt.strip()
    out["input"] = inp
    model = str(out.get("model", "")).strip().lower()
    vert = (
        "vertical 9:16 portrait video for Shorts, smartphone upright, "
        "tall frame, NOT landscape, NOT 16:9 widescreen"
    )
    prompt = str(inp.get("prompt", "")).strip()

    if model == "hailuo-2.3":
        inp["aspect_ratio"] = "9:16"
        res = str(inp.get("resolution", "768p")).strip().lower()
        dur_raw = inp.get("duration", 10)
        try:
            dur = int(dur_raw)
        except (TypeError, ValueError):
            dur = 10
        if dur not in (6, 10):
            dur = 10 if dur > 6 else 6
        if res == "1080p" and dur == 10:
            dur = 6
        inp["duration"] = dur
        inp["resolution"] = res
        if vert.lower()[:20] not in prompt.lower():
            inp["prompt"] = f"{prompt}, {vert}".strip(", ") if prompt else vert
    elif "seedance" in model:
        inp.setdefault("aspect_ratio", "9:16")
        if vert.lower()[:20] not in prompt.lower():
            inp["prompt"] = f"{prompt}, {vert}".strip(", ") if prompt else vert
    else:
        inp.setdefault("aspect_ratio", "9:16")
        if prompt and vert.lower()[:20] not in prompt.lower():
            inp["prompt"] = f"{prompt}, {vert}"

    return out


def start_trigger_server(config: AppConfig) -> None:
    logger = setup_logger()
    app = FastAPI()
    run_lock = threading.Lock()

    def _publish_main_and_shorts(payload: PublishVideoWithShortsRequest) -> dict:
        return publish_main_and_shorts_impl(config=config, logger=logger, payload=payload)

    def _publish_shorts_only(
        *,
        source_video_path: Path,
        track_for_metadata: str | None,
        theme: str | None,
        tags: list[str] | None,
        publish_at_iso: str | None,
        shorts_count: int,
        short_delay_hours: int,
        short_interval_hours: int,
        shorts_privacy_status: str,
        cleanup_source_after_publish: bool,
        cleanup_shorts_after_upload: bool,
        clip_seconds: int | None,
        clip_min_seconds: int | None,
        clip_max_seconds: int | None,
        tracks_dir_raw: str | None,
        output_dir_raw: str | None,
        youtube_oauth_profile: str | None = None,
    ) -> dict:
        tracks_dir = _resolve_tracks_dir(tracks_dir_raw, config)
        output_dir = _resolve_path(output_dir_raw, config.tiktok_output_dir)
        try:
            yt_refresh = resolve_youtube_refresh_token(config, youtube_oauth_profile)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        clips_target = max(1, shorts_count)
        effective_clip_seconds = config.tiktok_clip_seconds if clip_seconds is None else clip_seconds
        publish_base = _parse_publish_datetime(publish_at_iso)
        tags_seed = tags or config.content_tags

        meta_track_path = _resolve_source_video_path(track_for_metadata, config) if track_for_metadata else source_video_path
        base_meta = generate_metadata(meta_track_path, tags_seed, theme=theme)

        shorts = create_tiktok_cuts(
            source_video_path=source_video_path,
            tracks_dir=tracks_dir,
            output_dir=output_dir,
            clips_count=clips_target,
            clip_seconds=max(5, effective_clip_seconds),
            width=config.tiktok_width,
            height=config.tiktok_height,
            fps=config.fps,
            encode_preset=config.render_preset,
            crf=config.render_crf,
            clip_min_seconds=max(5, clip_min_seconds) if clip_min_seconds is not None else None,
            clip_max_seconds=max(5, clip_max_seconds) if clip_max_seconds is not None else None,
        )

        uploaded_shorts: list[dict] = []
        for index, short in enumerate(shorts):
            short_publish_at = publish_base + timedelta(hours=short_delay_hours + (short_interval_hours * index))
            short_meta = VideoMeta(
                title=f"{base_meta.title[:88]} · Short {index + 1}",
                description=base_meta.description,
                tags=list(dict.fromkeys(base_meta.tags + ["shorts"]))[:15],
            )
            upload_result = upload_video(
                video_path=short.output_path,
                meta=short_meta,
                client_id=config.youtube_client_id,
                client_secret=config.youtube_client_secret,
                refresh_token=yt_refresh,
                default_privacy=shorts_privacy_status,
                category_id=config.youtube_category_id,
                default_language=config.youtube_default_language,
                publish_at_iso=(
                    short_publish_at.isoformat().replace("+00:00", "Z")
                    if shorts_privacy_status == "private"
                    else ""
                ),
                channel_id=config.youtube_upload_channel_id,
                content_owner_id=config.youtube_content_owner_id,
                use_on_behalf_upload=config.youtube_use_on_behalf_upload,
                primary_refresh_token=config.youtube_refresh_token,
                fallback_to_primary_on_error=config.youtube_upload_fallback_to_primary,
            )
            short_url = f"https://www.youtube.com/shorts/{upload_result.video_id}"
            uploaded_shorts.append(
                {
                    "video_id": upload_result.video_id,
                    "status": upload_result.status,
                    "youtube_url": short_url,
                    "path": str(short.output_path),
                    "publish_at_iso": short_publish_at.isoformat().replace("+00:00", "Z"),
                    "start_second": short.start_second,
                    "duration_second": short.duration_second,
                }
            )
            if config.telegram_bot_token and config.telegram_chat_id:
                send_message_to_telegram(
                    bot_token=config.telegram_bot_token,
                    chat_id=config.telegram_chat_id,
                    message=short_url,
                )

        if cleanup_shorts_after_upload:
            for short in shorts:
                short.output_path.unlink(missing_ok=True)
        if cleanup_source_after_publish:
            source_video_path.unlink(missing_ok=True)

        return {
            "status": "ok",
            "message": "shorts uploaded",
            "shorts_count": len(uploaded_shorts),
            "shorts": uploaded_shorts,
            "schedule": {
                "short_delay_hours": short_delay_hours,
                "short_interval_hours": short_interval_hours,
            },
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "mode": "webhook"}

    @app.get("/tracks")
    def list_tracks(x_trigger_key: str | None = Header(default=None)) -> dict:
        """Sorted list of audio files under the resolved tracks dir (same discovery as video rendering)."""
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        tracks_dir = _resolve_tracks_dir(None, config)
        paths = [
            p
            for p in tracks_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        paths.sort(key=lambda p: p.relative_to(tracks_dir).as_posix().lower())
        rel = [p.relative_to(tracks_dir).as_posix() for p in paths]
        return {
            "tracks_dir": str(tracks_dir.resolve()),
            "count": len(rel),
            "tracks": rel,
        }

    @app.get("/workflow/n8n-short-publish-next")
    def n8n_short_publish_next(x_trigger_key: str | None = Header(default=None)) -> dict:
        """Next Short publish job for n8n (disk queue; does not use workflow staticData)."""
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")
        return peek_next_job(config.data_dir, config.n8n_short_publish_gap_ms)

    @app.post("/workflow/n8n-short-publish-ack")
    def n8n_short_publish_ack(x_trigger_key: str | None = Header(default=None)) -> dict:
        """Call after successful POST /workflow/publish-short for the current dequeue."""
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")
        return ack_publish(config.data_dir, config.n8n_short_publish_gap_ms)

    @app.post("/run")
    def run_now(payload: RunRequest, x_trigger_key: str | None = Header(default=None)) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            logger.info(
                "TRIGGER: manual run requested via webhook | track=%s allow_recent=%s tags=%s theme=%s",
                payload.track,
                payload.allow_recent_preferred,
                payload.tags,
                payload.theme,
            )
            pipeline_run(
                preferred_track=payload.track,
                allow_recent_preferred=payload.allow_recent_preferred,
                content_tags_override=payload.tags,
            )
            return {"status": "ok", "message": "run completed"}
        finally:
            run_lock.release()

    @app.post("/run-publish-with-shorts")
    def run_publish_with_shorts(
        payload: RunPublishWithShortsRequest,
        x_trigger_key: str | None = Header(default=None),
    ) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        store = create_state_store(config.state_db_path, database_url=config.database_url)
        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%dT%H%M%SZ")
        track_path_str = ""
        output_path_str = ""
        youtube_video_id = ""

        try:
            logger.info(
                "TRIGGER: run-publish-with-shorts | track=%s tags=%s shorts=%s delay=%s interval=%s",
                payload.track,
                payload.tags,
                payload.shorts_count,
                payload.short_delay_hours,
                payload.short_interval_hours,
            )

            effective_tags = [t.strip() for t in (payload.tags or config.content_tags) if t and t.strip()]
            if not effective_tags:
                effective_tags = config.content_tags

            bundle = render_pexels_track_bundle(
                config=config,
                store=store,
                logger=logger,
                effective_tags=effective_tags,
                preferred_track=payload.track,
                allow_recent_preferred=payload.allow_recent_preferred,
            )

            publish_payload = _publish_video_request_from_bundle_run(bundle, payload)

            publication = publish_main_and_shorts_impl(
                config=config,
                logger=logger,
                payload=publish_payload,
            )

            track_path_str = str(bundle.selected_track)
            output_path_str = str(bundle.render_result.output_path)
            youtube_video_id = publication.get("main_video", {}).get("video_id", "") or ""

            store.mark_track_used(track_path_str)
            store.mark_clips_used([c.source_url for c in bundle.clips])
            store.save_run(
                RunRecord(
                    run_id=run_id,
                    status="success",
                    track_path=track_path_str,
                    output_path=output_path_str,
                    youtube_video_id=youtube_video_id,
                    error_message="",
                    created_at=int(now.timestamp()),
                )
            )

            return {
                "status": "ok",
                "run_id": run_id,
                "track_path": track_path_str,
                "render_output_path": output_path_str,
                "render_stats": {
                    "planned_seconds": bundle.render_result.planned_seconds,
                    "final_target_seconds": bundle.render_result.final_target_seconds,
                },
                "publication": publication,
            }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: run-publish-with-shorts failed: %s", exc)
            store.save_run(
                RunRecord(
                    run_id=run_id,
                    status="error",
                    track_path=track_path_str,
                    output_path=output_path_str,
                    youtube_video_id=youtube_video_id,
                    error_message=str(exc),
                    created_at=int(now.timestamp()),
                )
            )
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            if config.cleanup_temp_after_run:
                _cleanup_temp_files(
                    temp_clips_dir=config.temp_clips_dir,
                    temp_renders_dir=config.temp_renders_dir,
                    keep_final_output=config.keep_final_output,
                )
            store.close()
            run_lock.release()

    @app.post("/workflow/render-main-and-shorts")
    def workflow_render_main_and_shorts(
        payload: RunPublishWithShortsRequest,
        x_trigger_key: str | None = Header(default=None),
    ) -> dict:
        """Рендер + YouTube long + нарезка шортов на диск. Шорты на YouTube — отдельно POST /workflow/publish-short из n8n."""
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        store = create_state_store(config.state_db_path, database_url=config.database_url)
        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%dT%H%M%SZ")
        track_path_str = ""
        output_path_str = ""
        youtube_video_id = ""

        try:
            effective_tags = [t.strip() for t in (payload.tags or config.content_tags) if t and t.strip()]
            if not effective_tags:
                effective_tags = config.content_tags

            bundle = render_pexels_track_bundle(
                config=config,
                store=store,
                logger=logger,
                effective_tags=effective_tags,
                preferred_track=payload.track,
                allow_recent_preferred=payload.allow_recent_preferred,
            )
            workflow_result = workflow_render_main_and_cut_shorts_impl(
                config=config,
                logger=logger,
                bundle=bundle,
                payload=payload,
            )

            persist_queue_after_render(
                config.data_dir,
                workflow_result,
                config.n8n_short_publish_gap_ms,
            )

            track_path_str = str(bundle.selected_track)
            output_path_str = str(bundle.render_result.output_path)
            youtube_video_id = workflow_result.get("main_video", {}).get("video_id", "") or ""

            store.mark_track_used(track_path_str)
            store.mark_clips_used([c.source_url for c in bundle.clips])
            store.save_run(
                RunRecord(
                    run_id=run_id,
                    status="success",
                    track_path=track_path_str,
                    output_path=output_path_str,
                    youtube_video_id=youtube_video_id,
                    error_message="",
                    created_at=int(now.timestamp()),
                )
            )

            return {
                "status": "ok",
                "run_id": run_id,
                "track_path": track_path_str,
                "render_output_path": output_path_str,
                "render_stats": {
                    "planned_seconds": bundle.render_result.planned_seconds,
                    "final_target_seconds": bundle.render_result.final_target_seconds,
                },
                "workflow": workflow_result,
            }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: workflow/render-main-and-shorts failed: %s", exc)
            store.save_run(
                RunRecord(
                    run_id=run_id,
                    status="error",
                    track_path=track_path_str,
                    output_path=output_path_str,
                    youtube_video_id=youtube_video_id,
                    error_message=str(exc),
                    created_at=int(now.timestamp()),
                )
            )
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            if config.cleanup_temp_after_run:
                _cleanup_temp_files(
                    temp_clips_dir=config.temp_clips_dir,
                    temp_renders_dir=config.temp_renders_dir,
                    keep_final_output=config.keep_final_output,
                )
            store.close()
            run_lock.release()

    @app.post("/workflow/publish-short")
    def workflow_publish_short(
        payload: WorkflowPublishShortRequest,
        x_trigger_key: str | None = Header(default=None),
    ) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            return workflow_publish_short_impl(config=config, logger=logger, payload=payload)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: workflow/publish-short failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            run_lock.release()

    @app.post("/tiktok-cuts")
    def tiktok_cuts(payload: TikTokCutsRequest, x_trigger_key: str | None = Header(default=None)) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            source_video_path = _resolve_source_video_path(payload.source_video_path, config)
            tracks_dir = _resolve_tracks_dir(payload.tracks_dir, config)
            output_dir = _resolve_path(payload.output_dir, config.tiktok_output_dir)

            clips_count = config.tiktok_clips_per_run if payload.clips_count is None else payload.clips_count
            clip_seconds = config.tiktok_clip_seconds if payload.clip_seconds is None else payload.clip_seconds
            clip_min_seconds = payload.clip_min_seconds
            clip_max_seconds = payload.clip_max_seconds

            logger.info(
                "TRIGGER: tiktok cuts requested | source=%s clips_count=%s clip_seconds=%s tracks_dir=%s output_dir=%s",
                source_video_path,
                clips_count,
                clip_seconds,
                tracks_dir,
                output_dir,
            )
            results = create_tiktok_cuts(
                source_video_path=source_video_path,
                tracks_dir=tracks_dir,
                output_dir=output_dir,
                clips_count=clips_count,
                clip_seconds=max(5, clip_seconds),
                width=config.tiktok_width,
                height=config.tiktok_height,
                fps=config.fps,
                encode_preset=config.render_preset,
                crf=config.render_crf,
                clip_min_seconds=max(5, clip_min_seconds) if clip_min_seconds is not None else None,
                clip_max_seconds=max(5, clip_max_seconds) if clip_max_seconds is not None else None,
            )
            response_payload = {
                "status": "ok",
                "message": "tiktok cuts completed",
                "clips_count": len(results),
                "clips": [
                    {
                        "path": str(item.output_path),
                        "track_path": str(item.track_path),
                        "start_second": item.start_second,
                        "duration_second": item.duration_second,
                    }
                    for item in results
                ],
            }
            if config.telegram_send_tiktok:
                # File uploads to Telegram for raw cuts are disabled; use publish-with-shorts for links.
                response_payload["telegram_sent"] = False
            return response_payload
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: tiktok cuts failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            run_lock.release()

    @app.post("/publish-video-with-shorts")
    def publish_video_with_shorts(
        payload: PublishVideoWithShortsRequest,
        x_trigger_key: str | None = Header(default=None),
    ) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            return _publish_main_and_shorts(payload)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: publish-video-with-shorts failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            run_lock.release()

    @app.post("/generate-poyo-and-publish")
    def generate_poyo_and_publish(
        payload: GeneratePoyoAndPublishRequest,
        x_trigger_key: str | None = Header(default=None),
    ) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            output_name = (payload.output_filename or f"poyo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.mp4").strip()
            output_path = (config.data_dir / "poyo_generated" / output_name).resolve()

            generation_result = generate_external_video(
                config=config,
                poyo_payload=payload.poyo_payload,
                output_path=output_path,
                segment_count=payload.poyo_stitch_segments,
            )
            generated_output_path = Path(str(generation_result.get("output_path", output_path)))

            publish_payload = PublishVideoWithShortsRequest(
                source_video_path=str(generated_output_path),
                track_for_metadata=payload.track_for_metadata,
                theme=payload.theme,
                tags=payload.tags,
                publish_at_iso=payload.publish_at_iso,
                shorts_count=payload.shorts_count,
                short_delay_hours=payload.short_delay_hours,
                short_interval_hours=payload.short_interval_hours,
                main_privacy_status=payload.main_privacy_status,
                shorts_privacy_status=payload.shorts_privacy_status,
                cleanup_source_after_publish=payload.cleanup_source_after_publish,
                cleanup_shorts_after_upload=payload.cleanup_shorts_after_upload,
                clip_seconds=payload.clip_seconds,
                clip_min_seconds=payload.clip_min_seconds,
                clip_max_seconds=payload.clip_max_seconds,
                tracks_dir=payload.tracks_dir,
                output_dir=payload.output_dir,
                youtube_oauth_profile=payload.youtube_oauth_profile,
            )
            publish_result = _publish_main_and_shorts(publish_payload)

            return {
                "status": "ok",
                "message": "poyo generated and published",
                "generation": generation_result,
                "publication": publish_result,
            }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: generate-poyo-and-publish failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            run_lock.release()

    @app.post("/generate-poyo-shorts-only")
    def generate_poyo_shorts_only(
        payload: GeneratePoyoShortsOnlyRequest,
        x_trigger_key: str | None = Header(default=None),
    ) -> dict:
        provided_key = x_trigger_key or ""
        if config.trigger_api_key and provided_key != config.trigger_api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

        if not run_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="run already in progress")

        try:
            output_name = (payload.output_filename or f"poyo_shorts_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.mp4").strip()
            output_path = (config.data_dir / "poyo_generated" / output_name).resolve()

            if payload.poyo_stitch_segments != 1:
                logger.info(
                    "TRIGGER: generate-poyo-shorts-only ignores poyo_stitch_segments=%s (using 1)",
                    payload.poyo_stitch_segments,
                )
            gen_payload = (
                _prepare_shorts_only_vertical_single_clip(payload.poyo_payload)
                if config.video_generation_provider == "poyo"
                else payload.poyo_payload
            )
            generation_result = generate_external_video(
                config=config,
                poyo_payload=gen_payload,
                output_path=output_path,
                segment_count=1,
            )
            generated_output_path = Path(str(generation_result.get("output_path", output_path)))
            shorts_result = _publish_shorts_only(
                source_video_path=generated_output_path,
                track_for_metadata=payload.track_for_metadata,
                theme=payload.theme,
                tags=payload.tags,
                publish_at_iso=payload.publish_at_iso,
                shorts_count=payload.shorts_count,
                short_delay_hours=payload.short_delay_hours,
                short_interval_hours=payload.short_interval_hours,
                shorts_privacy_status=payload.shorts_privacy_status,
                cleanup_source_after_publish=payload.cleanup_source_after_publish,
                cleanup_shorts_after_upload=payload.cleanup_shorts_after_upload,
                clip_seconds=payload.clip_seconds,
                clip_min_seconds=payload.clip_min_seconds,
                clip_max_seconds=payload.clip_max_seconds,
                tracks_dir_raw=payload.tracks_dir,
                output_dir_raw=payload.output_dir,
                youtube_oauth_profile=payload.youtube_oauth_profile,
            )

            return {
                "status": "ok",
                "message": "poyo generated and shorts published",
                "generation": generation_result,
                "publication": shorts_result,
            }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRIGGER: generate-poyo-shorts-only failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            run_lock.release()

    logger.info("TRIGGER: server started on 0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


def _resolve_path(raw: str | None, default_path: Path) -> Path:
    fallback = Path(default_path)
    if raw is None or not raw.strip():
        return fallback
    candidate = Path(raw.strip())
    if candidate.is_absolute():
        return candidate
    return (fallback / candidate).resolve()


def _resolve_source_video_path(raw: str, config: AppConfig) -> Path:
    requested = Path(raw.strip())
    search_dirs = [
        config.assets_source_videos_dir,
        Path("/assets/source_videos"),
        Path("/storage/videos"),
        config.data_dir / "videos",
    ]

    # 1) If absolute and exists, use as-is.
    if requested.is_absolute() and requested.exists():
        return requested

    # 2) Try exact relative path under known directories.
    if not requested.is_absolute():
        for base in search_dirs:
            candidate = (base / requested).resolve()
            if candidate.exists():
                return candidate

    # 3) Try by filename only across known directories.
    filename = requested.name
    for base in search_dirs:
        candidate = (base / filename).resolve()
        if candidate.exists():
            return candidate

    # Keep the original path in error for clear debugging.
    return requested


def _resolve_tracks_dir(raw: str | None, config: AppConfig) -> Path:
    if raw and raw.strip():
        return _resolve_path(raw, config.assets_tracks_dir)

    candidates = [
        config.assets_tracks_dir,
        Path("/assets/tracks"),
        Path("/storage/tracks"),
    ]
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return config.assets_tracks_dir


def _parse_publish_datetime(raw: str | None) -> datetime:
    if raw and raw.strip():
        normalized = raw.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)
