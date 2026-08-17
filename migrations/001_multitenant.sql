-- 001: мультиарендная схема для ТГ-сервиса нарезки шортсов.
--
-- Существующие used_tracks / used_clips / runs НЕ трогаем: они обслуживают
-- лофи-конвейер (подбор треков + сток Pexels), который к этому продукту
-- отношения не имеет и продолжает работать как есть.

CREATE TABLE IF NOT EXISTS users (
    id                BIGSERIAL PRIMARY KEY,
    tg_user_id        BIGINT      NOT NULL UNIQUE,
    tg_username       TEXT,
    plan              TEXT        NOT NULL DEFAULT 'free',
    -- active | suspended | banned. suspended ставится автоматически при
    -- копирайт-инциденте, banned — руками.
    status            TEXT        NOT NULL DEFAULT 'active',
    status_reason     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS youtube_accounts (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel_id        TEXT,
    channel_title     TEXT,
    -- Шифруется на стороне приложения. В открытом виде не хранится никогда.
    refresh_token_enc BYTEA       NOT NULL,
    scopes            TEXT[]      NOT NULL DEFAULT '{}',
    connected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ
);

-- Один активный канал на юзера; отозванные не мешают переподключиться.
CREATE UNIQUE INDEX IF NOT EXISTS youtube_accounts_active_uniq
    ON youtube_accounts (user_id, channel_id)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS sources (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    storage_key         TEXT        NOT NULL,
    original_filename   TEXT,
    size_bytes          BIGINT,
    duration_s          INTEGER,
    -- awaiting_upload | uploaded | transcribing | analyzing | ready | failed
    status              TEXT        NOT NULL DEFAULT 'awaiting_upload',
    error               TEXT,
    -- Подтверждение прав на контент. Без него конвейер не стартует —
    -- это же поле показывается на ревью Google.
    rights_confirmed_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sources_user_idx ON sources (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id          BIGSERIAL PRIMARY KEY,
    source_id   BIGINT  NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    start_ms    INTEGER NOT NULL,
    end_ms      INTEGER NOT NULL,
    text        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS transcript_source_idx
    ON transcript_segments (source_id, start_ms);

CREATE TABLE IF NOT EXISTS highlights (
    id          BIGSERIAL PRIMARY KEY,
    source_id   BIGINT  NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    start_ms    INTEGER NOT NULL,
    end_ms      INTEGER NOT NULL,
    score       REAL    NOT NULL DEFAULT 0,
    -- Чем обосновано попадание в хайлайты — для отладки качества отбора.
    reason      TEXT,
    title       TEXT,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Планировщик берёт следующий неиспользованный хайлайт по убыванию score.
CREATE INDEX IF NOT EXISTS highlights_pick_idx
    ON highlights (source_id, score DESC)
    WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS schedules (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id      BIGINT      NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    -- Периодичность, которую юзер выставляет в боте. Меняется здесь,
    -- а не правкой воркфлоу n8n.
    every_hours    INTEGER     NOT NULL CHECK (every_hours > 0),
    next_run_at    TIMESTAMPTZ NOT NULL,
    max_shorts     INTEGER,
    produced_count INTEGER     NOT NULL DEFAULT 0,
    -- v1: всегда false, шортсы отдаём в ТГ. Включится на этапе 2,
    -- когда придёт расширение квоты YouTube.
    autopublish    BOOLEAN     NOT NULL DEFAULT false,
    privacy        TEXT        NOT NULL DEFAULT 'private',
    active         BOOLEAN     NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS schedules_due_idx
    ON schedules (next_run_at)
    WHERE active;

CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id       BIGINT      NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    highlight_id    BIGINT      REFERENCES highlights(id) ON DELETE SET NULL,
    schedule_id     BIGINT      REFERENCES schedules(id) ON DELETE SET NULL,
    -- pending | rendering | delivering | uploading | done | failed
    state           TEXT        NOT NULL DEFAULT 'pending',
    attempts        INTEGER     NOT NULL DEFAULT 0,
    -- Аренда воркера: два n8n Worker'а не должны взять одну задачу.
    locked_at       TIMESTAMPTZ,
    locked_by       TEXT,
    output_key      TEXT,
    youtube_video_id TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_queue_idx ON jobs (state, created_at);
CREATE INDEX IF NOT EXISTS jobs_user_idx  ON jobs (user_id, created_at DESC);

-- Страховка от копирайт-инцидентов: после публикации дёргаем
-- videos.list?part=status (1 юнит) и смотрим rejectionReason.
CREATE TABLE IF NOT EXISTS publish_checks (
    id               BIGSERIAL PRIMARY KEY,
    job_id           BIGINT      NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    youtube_video_id TEXT        NOT NULL,
    upload_status    TEXT,
    -- copyright | claim | trademark | legal | inappropriate | ...
    rejection_reason TEXT,
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS publish_checks_job_idx ON publish_checks (job_id);

-- Собственный учёт расхода квоты: упереться в свой лимит надо раньше,
-- чем один активный юзер выжрет общие 10 000 юнитов на всех.
CREATE TABLE IF NOT EXISTS usage_daily (
    user_id   BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day       DATE    NOT NULL,
    uploads   INTEGER NOT NULL DEFAULT 0,
    api_units INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- Ответ на запрос Google «что это за видео» должен занимать минуту.
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT        NOT NULL,
    entity     TEXT,
    entity_id  BIGINT,
    meta       JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_log_user_idx ON audit_log (user_id, created_at DESC);
