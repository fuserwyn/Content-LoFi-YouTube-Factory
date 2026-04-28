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


1) Product/контент стратегия
Зафиксировать формат канала: длина роликов, частота, стиль (nature/surf/lofi).
Определить KPI: просмотры, CTR, watch time, retention, RPM.
Сделать контент-план на 30 дней (темы, mood, время публикации).
Описать правила нейминга видео и плейлистов.
2) Легальность и безопасность
Подтвердить лицензии источников видео (Pexels/Pixabay/платные стоки).
Зафиксировать политику атрибуции (когда обязательна и в каком формате).
Добавить хранение лицензий в run-report (source_url, author, license).
Настроить проверку “не брать запрещенный контент/бренды/лица без прав”.
Подготовить шаблон ответа на possible copyright claim.
3) Инфраструктура проекта
Довести структуру репозитория до production-ready (src/tests/scripts/docs).
Добавить Makefile/скрипты run, test, lint, format.
Настроить pre-commit (ruff/black/pytest).
Добавить версионирование release notes (changelog).
4) Конфигурация и секреты
Заполнить .env по .env.example.
Настроить секреты в Railway Variables.
Вынести все runtime-параметры в env (duration, tags, schedule, retries).
Добавить валидацию env с понятными ошибками.
5) Музыкальная библиотека
Загрузить треки в assets/tracks.
Добавить метаданные треков (title, bpm, mood, duration, is_released).
Реализовать политику выбора трека (anti-repeat + mood-based).
Добавить проверку качества аудио (битрейт, отсутствие клиппинга).
6) Пайплайн видео-ассетов
Расширить загрузчик клипов (несколько запросов, pagination, retries).
Улучшить фильтрацию клипов (fps, ориентация, артефакты, watermark risk).
Добавить дедупликацию по source id/url/hash.
Настроить очистку временных файлов после успешного run.
7) Рендер и монтаж
Улучшить FFmpeg pipeline: кроссфейды, стабилизация loudness, target LUFS.
Добавить режимы роликов (15/30/60 min preset).
Добавить template overlay (название трека/канал).
Добавить автогенерацию thumbnail (кадр + текст).
Валидация финального файла (codec, duration, resolution).
8) Метаданные и SEO
Шаблоны title/description/tags под разные “mood scenes”.
Генерация 2–3 вариантов title и выбор лучшего по правилам.
Добавить playlist assignment при upload.
Добавить стандартные блоки в description (credits, links, hashtags).
Подготовить мультиязычный режим (RU/EN).
9) YouTube API интеграция
Завершить OAuth setup (refresh token, scopes, test upload).
Добавить private -> scheduled -> public flow.
Реализовать retry для resumable upload.
Добавить сохранение video_id, publishedAt, privacyStatus.
Добавить защиту от повторной загрузки одного и того же файла.
10) Оркестрация и расписание (Railway)
Задеплоить сервис в Railway по Dockerfile.
Настроить Cron Job (например, каждые 72 часа).
Проверить перезапуски и retry policy.
Настроить persistent storage или внешний DB для state.
Сделать dry-run задачу (без upload) для безопасной проверки.
11) Хранилище состояния и отчеты
Расширить state.db (таблицы: assets, renders, uploads, failures).
Сохранять полный run-report в data/runs.
Добавить статус-машину run (started/failed/rendered/uploaded/scheduled).
Добавить миграции схемы БД.
Добавить экспорт отчета в JSON/CSV.
12) Наблюдаемость и алерты
Структурированные логи по этапам.
Добавить метрики по длительности этапов.
Уведомления в Telegram/Discord: success/fail + причина.
Алерт при N подряд неудачных запусков.
Dashboard для последних запусков и статусов.
13) Тестирование (обязательно)
Unit tests для всех модулей (часть уже сделана).
Integration tests с моками Pexels/YouTube/FFmpeg.
E2E dry-run тест полного пайплайна.
Smoke test после деплоя на Railway.
Регулярный запуск тестов в CI.
14) CI/CD
Настроить GitHub Actions: lint + tests + build image.
Проверка Docker сборки на каждом PR.
Автодеплой в Railway из main.
Environment promotion (staging -> production).
Политика rollback.
15) Анти-спам и качество канала
Правила уникальности контента (не повторять клипы слишком часто).
Авто-микс сцены/треки для различий между роликами.
Разные шаблоны thumbnail/title.
Контроль “reused content risk”.
Регулярный аудит последних публикаций.
16) Аналитика и оптимизация
Сбор YouTube Analytics (CTR, retention, avg view duration).
A/B тестирование title/thumbnail.
Правила авто-коррекции (если CTR низкий -> менять стиль title).
Подбор лучших временных окон публикации.
Еженедельный auto-report.
17) Документация и эксплуатация
OPERATIONS.md: как запускать, дебажить, восстанавливать.
INCIDENTS.md: типовые ошибки и что делать.
Четкий onboarding чеклист.
Runbook для ручного override публикации.
План развития v2 (multi-platform, AI editor, dashboard UI).