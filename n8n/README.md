# n8n Workflow Templates

This folder contains ready-to-import workflows for triggering Content Factory:

- `workflows/content-factory-manual-run.json` - manual trigger button in n8n
- `workflows/content-factory-scheduled-run.json` - scheduled daily trigger (20:00 Kyiv / 17:00 UTC)
- `workflows/content-factory-30-day-plan.json` - 30-day daily plan (track + tags + theme)
- `workflows/content-factory-tiktok-cuts-manual.json` - manual TikTok cuts from an existing source video
- `workflows/content-factory-30-day-main-plus-shorts.json` - separate daily workflow: 1 main video + 3 shorts from the same source
- `workflows/content-factory-22-tracks-every-3-days-main-plus-shorts.json` - separate workflow for 22 tracks: 1 main every 3 days + 1 short per day (3 shorts total)
- `workflows/content-factory-poyo-generate-and-publish.json` - generate one video with Poyo API and publish it with shorts
- `workflows/content-factory-poyo-shorts-test.json` - test workflow: generate one Poyo video and publish shorts only

## Required n8n environment variables

Set these in the n8n service:

- `CONTENT_FACTORY_RUN_URL=https://<content-factory-domain>/run`
- `CONTENT_FACTORY_TIKTOK_CUTS_URL=https://<content-factory-domain>/tiktok-cuts`
- `CONTENT_FACTORY_PUBLISH_WITH_SHORTS_URL=https://<content-factory-domain>/publish-video-with-shorts`
- `CONTENT_FACTORY_POYO_GENERATE_AND_PUBLISH_URL=https://<content-factory-domain>/generate-poyo-and-publish`
- `CONTENT_FACTORY_POYO_SHORTS_ONLY_URL=https://<content-factory-domain>/generate-poyo-shorts-only`
- `TRIGGER_API_KEY=<same value as Content Factory TRIGGER_API_KEY>`

## Import via n8n UI

1. Open n8n -> Workflows
2. Click `Import from file`
3. Import both JSON files from `n8n/workflows/`
4. Open each workflow and confirm URL/key expressions are present
5. Activate workflow(s)

## Notes

- Keep Content Factory in webhook mode:
  - `RUN_MODE=webhook`
- Scheduled workflow uses cron `0 17 * * *` (17:00 UTC).
- You can modify the schedule in the Cron node.
- For the 30-day workflow:
  - Open node `Pick Day Plan Item`
  - Replace placeholder `track-01.mp3` ... `track-30.mp3` with your real track filenames
  - Replace tags/themes with your own content plan
- For the TikTok cuts workflow:
  - Open node `Set TikTok Payload`
  - Set `source_video_path` to the absolute path in your storage/volume
  - `clips_count=0` enables auto split into as many clips as source video allows
  - Optional: set `clip_min_seconds` and `clip_max_seconds` for varied clip lengths
  - Optional: set `tracks_dir`, `output_dir`
  - If `TELEGRAM_SEND_TIKTOK=true`, clips are sent to Telegram one by one as each clip finishes
- For the 30-day main+shorts workflow:
  - Open node `Build Day Payload`
  - Replace `/storage/videos/day-01.mp4` ... `/storage/videos/day-30.mp4` with your real files
  - Keep `shorts_count=3`, `short_delay_hours=1`, `short_interval_hours=7` for the required schedule
  - Workflow calls `/publish-video-with-shorts` once per day; shorts schedule is handled by backend endpoint
- For the 22-tracks every-3-days workflow:
  - Open node `Build 22-Track Cycle Payload`
  - Replace `/storage/videos/track-01.mp4` ... `/storage/videos/track-22.mp4` with your real files
  - Track names from `assets/tracks` are already prefilled into `track_for_metadata`
  - Cron runs daily, but node publishes only on every 3rd day (stable 72h cadence)
  - Main video is sent with `main_privacy_status=public` (published immediately)
  - Shorts are sent with `shorts_privacy_status=private` and scheduled at +24h, +48h, +72h
  - Cleanup flags are enabled by default in payload:
    - `cleanup_source_after_publish=true`
    - `cleanup_shorts_after_upload=true`
- For the Poyo workflow:
  - Set `POYO_API_KEY` in Content Factory env (you can add later)
  - Open node `Set Poyo Input` and update `prompt`, `theme`, `track_for_metadata`
  - Endpoint `/generate-poyo-and-publish` generates video via Poyo, then publishes main+shorts using the same pipeline
- For the Poyo shorts-only test workflow:
  - Start with `workflows/content-factory-poyo-shorts-test.json`
  - It calls `/generate-poyo-shorts-only` and publishes only shorts (no long video upload)
  - After validation, duplicate this workflow and scale to schedule/campaign pipeline
