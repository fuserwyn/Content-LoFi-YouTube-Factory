from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import traceback

from .config import load_config
from .fetch_assets import fetch_and_download_clips, load_local_clips
from .generate_meta import generate_metadata
from .logger import setup_logger
from .notify_n8n import send_run_notification
from .render_video import render_video_with_ffmpeg
from .select_track import choose_track
from .state_store import RunRecord, create_state_store
from .upload_youtube import upload_video


def _write_run_report(report_path: Path, payload: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=True, indent=2)


def _cleanup_temp_files(temp_clips_dir: Path, temp_renders_dir: Path, keep_final_output: bool) -> None:
    for file_path in temp_clips_dir.glob("*"):
        if file_path.is_file():
            file_path.unlink(missing_ok=True)

    for path in temp_renders_dir.glob("*"):
        if keep_final_output and path.name == "final.mp4":
            continue
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def run() -> None:
    logger = setup_logger()
    config = load_config()
    store = create_state_store(config.state_db_path, database_url=config.database_url)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    report_path = config.runs_dir / f"{run_id}.json"

    logger.info("Starting run_id=%s", run_id)
    report_payload: dict = {
        "run_id": run_id,
        "started_at": now.isoformat(),
        "status": "started",
    }

    track_path = ""
    output_path = ""
    youtube_video_id = ""

    try:
        recent_tracks = set(store.recent_tracks(config.max_recent_track_lookback))
        recent_clips = set(store.recent_clips(config.max_recent_clip_lookback))

        clips = []
        if config.use_local_videos_only:
            logger.info("FETCH: loading clips from local source videos")
            clips = load_local_clips(
                source_dir=config.assets_source_videos_dir,
                max_clips=config.max_clips_per_run,
                min_clip_seconds=config.min_clip_seconds,
                min_width=config.target_width,
                min_height=config.target_height,
                recently_used_clip_urls=recent_clips,
            )
            if not clips and config.local_videos_fallback_to_pexels:
                logger.info("FETCH: local clips unavailable, falling back to Pexels")

        if (not clips) and (not config.use_local_videos_only or config.local_videos_fallback_to_pexels):
            logger.info("FETCH: requesting clips from Pexels")
            clips = fetch_and_download_clips(
                api_key=config.pexels_api_key,
                tags=config.content_tags,
                output_dir=config.temp_clips_dir,
                max_clips=config.max_clips_per_run,
                min_clip_seconds=config.min_clip_seconds,
                min_width=config.target_width,
                min_height=config.target_height,
                recently_used_clip_urls=recent_clips,
                per_page=config.pexels_per_page,
                pages_per_tag=config.pexels_pages_per_tag,
            )
        if not clips:
            raise RuntimeError("No valid clips available from local source videos or Pexels.")

        logger.info("TRACK_SELECT: selecting music track")
        selected_track = choose_track(config.assets_tracks_dir, recent_tracks)
        track_path = str(selected_track)

        logger.info("RENDER: composing final video with FFmpeg")
        render_result = render_video_with_ffmpeg(
            clips=clips,
            track_path=selected_track,
            output_dir=config.temp_renders_dir,
            target_duration_seconds=config.target_duration_min * 60,
            width=config.target_width,
            height=config.target_height,
            fps=config.fps,
            encode_preset=config.render_preset,
            crf=config.render_crf,
        )
        output_path = str(render_result.output_path)

        logger.info("META: generating title/description/tags")
        meta = generate_metadata(selected_track, config.content_tags)
        report_payload["metadata"] = asdict(meta)

        if config.upload_enabled:
            logger.info("UPLOAD: uploading to YouTube")
            upload_result = upload_video(
                video_path=render_result.output_path,
                meta=meta,
                client_id=config.youtube_client_id,
                client_secret=config.youtube_client_secret,
                refresh_token=config.youtube_refresh_token,
                default_privacy=config.youtube_default_privacy,
                category_id=config.youtube_category_id,
                default_language=config.youtube_default_language,
                publish_at_iso=config.publish_at_iso,
            )
            youtube_video_id = upload_result.video_id
            report_payload["upload"] = {
                "status": upload_result.status,
                "video_id": upload_result.video_id,
            }
        else:
            report_payload["upload"] = {"status": "skipped", "reason": "UPLOAD_ENABLED=false"}

        logger.info("STATE_SAVE: marking used assets")
        store.mark_track_used(track_path)
        store.mark_clips_used([c.source_url for c in clips])
        report_payload["clips"] = [
            {
                "source_video_id": c.source_video_id,
                "source_url": c.source_url,
                "download_url": c.download_url,
                "author_name": c.author_name,
                "license": c.license,
                "local_path": str(c.local_path),
            }
            for c in clips
        ]
        report_payload["status"] = "success"

        store.save_run(
            RunRecord(
                run_id=run_id,
                status="success",
                track_path=track_path,
                output_path=output_path,
                youtube_video_id=youtube_video_id,
                error_message="",
                created_at=int(now.timestamp()),
            )
        )
        logger.info("Run completed successfully run_id=%s", run_id)
    except Exception as exc:  # noqa: BLE001
        error_text = f"{exc}\n{traceback.format_exc()}"
        report_payload["status"] = "error"
        report_payload["error"] = error_text
        store.save_run(
            RunRecord(
                run_id=run_id,
                status="error",
                track_path=track_path,
                output_path=output_path,
                youtube_video_id=youtube_video_id,
                error_message=str(exc),
                created_at=int(now.timestamp()),
            )
        )
        logger.error("Run failed run_id=%s error=%s", run_id, exc)
        raise
    finally:
        report_payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_run_report(report_path, report_payload)
        try:
            send_run_notification(config.n8n_webhook_url, report_payload)
        except Exception as notify_exc:  # noqa: BLE001
            logger.warning("Failed to notify n8n webhook: %s", notify_exc)
        if config.cleanup_temp_after_run:
            _cleanup_temp_files(
                temp_clips_dir=config.temp_clips_dir,
                temp_renders_dir=config.temp_renders_dir,
                keep_final_output=config.keep_final_output,
            )
        store.close()


if __name__ == "__main__":
    run()
