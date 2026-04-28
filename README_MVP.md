# Content Factory MVP (Railway)

## Goal
Build an automated pipeline that:
- downloads licensed stock clips (nature/surf/ocean),
- combines them with your lo-fi track,
- generates YouTube metadata,
- uploads video as scheduled content.

MVP focuses on stability and repeatable automation first, visuals second.

## MVP Scope
- One command runs full pipeline end-to-end.
- One output video per run.
- Basic transitions and clean audio normalization.
- Upload to YouTube as `private` or `scheduled`.
- Keep usage history to avoid duplicate clips/tracks.

Out of scope for v1:
- complex AI editing decisions,
- multi-platform posting (TikTok/Reels),
- advanced web UI dashboard.

## Tech Stack
- Language: `Python 3.11+`
- Video rendering: `FFmpeg`
- Source API: `Pexels API` (expand later to Pixabay/paid stock)
- YouTube upload: `YouTube Data API v3` (`google-api-python-client`)
- Runtime/deploy: `Railway`
- Scheduling: `Railway Cron`
- State storage: `SQLite` (or JSON in MVP fallback)

## Project Structure
```text
content-factory/
  src/
    main.py                 # Orchestrates the whole pipeline
    config.py               # Env loading + validation
    fetch_assets.py         # Search/download clips from Pexels
    select_track.py         # Select next music track
    render_video.py         # Build final video via FFmpeg
    generate_meta.py        # Title/description/hashtags templates
    upload_youtube.py       # Upload + schedule publish
    state_store.py          # Read/write used clips/tracks + run history
    logger.py               # Logging setup
  assets/
    tracks/                 # Your lo-fi tracks (input)
    fonts/                  # Optional overlay font files
  data/
    state.db                # SQLite database
    runs/                   # Per-run JSON reports
  temp/
    clips/                  # Downloaded stock clips (ephemeral)
    renders/                # Intermediate render files
  requirements.txt
  Dockerfile
  railway.json              # Optional cron/start config
  .env.example
  README_MVP.md
```

## High-Level Architecture
1. `Scheduler` (Railway Cron) triggers `python -m src.main`.
2. `main.py` calls each module in order.
3. `fetch_assets.py` fetches and downloads matching clips.
4. `select_track.py` picks a track not recently used.
5. `render_video.py` composes final MP4 with FFmpeg.
6. `generate_meta.py` builds YouTube title/description/tags.
7. `upload_youtube.py` uploads and schedules publish time.
8. `state_store.py` saves what was used and run outcome.

## Data Flow
1. Input:
   - tags (`nature`, `surf`, `ocean`, etc.),
   - target duration,
   - local music library.
2. Processing:
   - API search -> filter -> download clips,
   - select track,
   - render video,
   - generate metadata.
3. Output:
   - final MP4,
   - thumbnail (optional in v1),
   - YouTube video ID,
   - run report.

## Environment Variables (`.env`)
```env
# Pexels
PEXELS_API_KEY=

# YouTube OAuth
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=

# Channel / upload defaults
YOUTUBE_DEFAULT_PRIVACY=private
YOUTUBE_CATEGORY_ID=10
YOUTUBE_DEFAULT_LANGUAGE=en

# Render settings
TARGET_DURATION_MIN=30
TARGET_WIDTH=1920
TARGET_HEIGHT=1080
FPS=30

# Scheduler/business logic
MAX_CLIPS_PER_RUN=20
MIN_CLIP_SECONDS=5
MAX_RECENT_TRACK_LOOKBACK=10
MAX_RECENT_CLIP_LOOKBACK=100
```

## Pipeline Order (Execution Sequence)
1. Validate config and required keys.
2. Load current state (recent clips/tracks history).
3. Fetch candidate clips from Pexels by tags.
4. Filter clips:
   - landscape orientation,
   - at least 1080p,
   - not recently used.
5. Download selected clips to `temp/clips/`.
6. Select one track from `assets/tracks/` not recently used.
7. Build FFmpeg concat/timeline to match target duration.
8. Render final video to `temp/renders/final_<timestamp>.mp4`.
9. Generate title + description + tags.
10. Upload to YouTube (private or scheduled publish).
11. Save run report and update state DB.

## Railway Deployment Architecture
- Single worker service (no web server needed for MVP).
- Command executed by cron:
  - `python -m src.main`
- Add persistent volume if you want long-term local state retention.
- If no persistent volume:
  - store state in external DB later (Supabase/Postgres),
  - or accept reset behavior after redeploy.

## Build/Runtime Requirements
- `ffmpeg` must be available in runtime image.
- Python dependencies from `requirements.txt`.
- Tracks are present in `assets/tracks/` before run.

## Error Handling Strategy (MVP)
- If clip download fails -> skip and continue.
- If too few valid clips -> fail run with clear log.
- If render fails -> stop and write error report.
- If YouTube upload fails -> keep rendered file + retry on next run.
- Always write `data/runs/<timestamp>.json` summary.

## Logging and Observability
- Structured logs per stage:
  - `FETCH`, `TRACK_SELECT`, `RENDER`, `META`, `UPLOAD`, `STATE_SAVE`.
- Final run summary includes:
  - selected track,
  - source clip IDs/URLs,
  - output file path,
  - upload status/video ID,
  - error (if any).

## Safety and Licensing
- Use only clips with license suitable for commercial use.
- Save attribution/license data per clip in run report.
- Never use copyrighted third-party music.
- Keep audit trail to respond to platform claims.

## Implementation Roadmap
### Phase 1 - Core pipeline
- Implement config, fetch, track select, render, upload.
- Manual run from local machine until one successful upload.

### Phase 2 - Railway
- Containerize and deploy to Railway.
- Configure env vars and schedule cron.
- Verify one automated scheduled upload.

### Phase 3 - Reliability
- Add retry/backoff for API failures.
- Add duplicate prevention and better filtering.
- Add Telegram/Discord notifications on success/failure.

## Definition of Done (MVP)
- A scheduled Railway job runs without manual actions.
- One complete video is created from stock clips + your track.
- Video is uploaded to YouTube with metadata.
- State is updated so next run avoids same assets.
- Run report is saved for every execution.
