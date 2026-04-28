# Content Factory MVP - 7 Day Backlog

Status note:
- `1) Product/content strategy` - DONE
- `2) Legal and safety` - DONE

This backlog starts from technical implementation tasks after strategy/legal alignment.

## Priorities
- `P0` - must have for working autonomous pipeline
- `P1` - important reliability improvements
- `P2` - nice to have for next iteration

## Day 1 - Config and local run foundation
- `[P0]` Finalize runtime config and secrets handling
  - Validate all required env vars on startup
  - Add clear error messages for missing/invalid vars
- `[P0]` Prepare local assets and bootstrap scripts
  - Ensure `assets/tracks` has valid audio files
  - Add helper commands for run/test/lint
- `[P1]` Add project operation docs
  - Local quickstart and first run checklist

Definition of done:
- `python -m src.main` starts and validates config cleanly
- New developer can run project locally using docs

## Day 2 - Video sourcing pipeline hardening
- `[P0]` Improve clip fetch behavior
  - Add pagination and multi-query fetch
  - Add retry/backoff for transient API/network errors
- `[P0]` Improve filtering quality
  - Keep landscape-only, min resolution constraints
  - Skip recently used assets by state history
- `[P1]` Add asset deduplication
  - Deduplicate by source URL and source ID

Definition of done:
- Fetch step consistently returns valid candidate clips
- Repeated runs avoid immediate clip reuse

## Day 3 - Render quality and output validation
- `[P0]` Harden FFmpeg render pipeline
  - Stable concat timeline
  - Correct scaling/cropping for target output
  - Audio attach and final duration cap
- `[P1]` Add output validation
  - Verify output exists, non-zero size, expected extension
  - Basic probe checks for resolution/duration
- `[P2]` Add optional text overlay template

Definition of done:
- Each run produces a playable final MP4 with expected format

## Day 4 - Metadata and YouTube publishing flow
- `[P0]` Finalize metadata generation templates
  - Title/description/tags limits and formatting
- `[P0]` Stabilize YouTube upload integration
  - Upload as `private` by default
  - Optional scheduled publish via env
- `[P1]` Add playlist assignment support

Definition of done:
- End-to-end flow uploads one generated video to YouTube test channel

## Day 5 - State, reports, and observability
- `[P0]` Extend run report content
  - Include selected track, clip list, metadata, upload status
  - Persist licensing fields (`source_url`, `author`, `license`)
- `[P0]` Improve DB/state robustness
  - Track run statuses and failures
  - Keep anti-duplicate history for tracks/clips
- `[P1]` Add structured stage logs and timing

Definition of done:
- Every run has a saved JSON report + DB record
- Failures can be diagnosed from logs and report

## Day 6 - Tests and CI baseline
- `[P0]` Expand automated tests
  - Integration tests with mocks for Pexels and YouTube
  - Error-path tests for fetch/render/upload failures
- `[P0]` Add CI checks
  - Run tests and syntax checks on each push/PR
- `[P1]` Add coverage threshold target

Definition of done:
- CI passes on main branch
- Core pipeline behavior protected by automated tests

## Day 7 - Railway deploy and scheduled automation
- `[P0]` Deploy worker service to Railway
  - Configure env vars and start command
  - Verify Docker build and runtime ffmpeg availability
- `[P0]` Configure Railway Cron
  - Scheduled run every 48-72 hours
  - Verify at least one autonomous scheduled execution
- `[P1]` Add notifications
  - Telegram/Discord success/failure summary

Definition of done:
- Fully autonomous scheduled pipeline runs on Railway
- Successful run uploads content and writes report/state

---

## Backlog After Week 1 (Next Iteration)
- `[P1]` Better clip quality scoring and scene diversity
- `[P1]` Thumbnail generation and A/B title variants
- `[P1]` YouTube analytics ingestion (CTR, retention, watch time)
- `[P2]` Auto-optimization loop based on KPI thresholds
- `[P2]` Multi-platform publishing (shorts/reels/tiktok) with separate policy

## Execution Rules
- Work sequentially: finish `P0` of the current day before `P1/P2`
- After each completed task:
  - write or update tests
  - run tests locally
  - save result in run notes
- Do not move to next day with failing tests
