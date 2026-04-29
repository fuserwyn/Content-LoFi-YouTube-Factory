# n8n Workflow Templates

This folder contains ready-to-import workflows for triggering Content Factory:

- `workflows/content-factory-manual-run.json` - manual trigger button in n8n
- `workflows/content-factory-scheduled-run.json` - scheduled daily trigger (20:00 Kyiv / 17:00 UTC)
- `workflows/content-factory-30-day-plan.json` - 30-day daily plan (track + tags + theme)

## Required n8n environment variables

Set these in the n8n service:

- `CONTENT_FACTORY_RUN_URL=https://<content-factory-domain>/run`
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
