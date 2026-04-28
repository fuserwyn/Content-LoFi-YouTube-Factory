# Railway Quickstart

## 1. Environment Variables
Set all variables from `.env.example` in Railway service variables.

Required minimum:
- `PEXELS_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

Optional but recommended on Railway:
- `DATABASE_URL` (Railway Postgres connection string)
- `N8N_WEBHOOK_URL` (for run notifications)

## 2. Build and Start
- Build uses `Dockerfile`
- Start command: `python -m src.main`

## 3. Test run before scheduling
Run one dry run first:
- `UPLOAD_ENABLED=false`
- Trigger deploy run

Then enable upload:
- `UPLOAD_ENABLED=true`

## 4. Schedule
Create a Railway cron that runs every 48-72 hours and calls:
- `python -m src.main`

## 5. Verify outputs
After each run, verify:
- logs in Railway
- report JSON in `data/runs` (if persistent volume enabled)
- new row in DB state tables
- uploaded video on YouTube channel
