"""Доступ к мультиарендной схеме — то, через что работают бот и планировщик.

Схема заведена в ``migrations/001_multitenant.sql``; здесь только операции над
ней. Существующий ``state_store`` не трогаем: он обслуживает лофи-конвейер
(подбор треков, сток Pexels) и к этому продукту отношения не имеет.

Ключевая операция — ``claim_jobs``. Задачи разбираются через
``FOR UPDATE SKIP LOCKED``, иначе два воркера возьмут одну и ту же и юзер
получит два одинаковых шортса за свои деньги.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from .highlights import Highlight
from .transcribe import TranscriptSegment, Word

# Дольше этого джоба считается брошенной: воркер упал или его убили, и её
# нужно вернуть в очередь, иначе она зависнет в rendering навсегда.
STALE_LOCK_SECONDS = 3600

MAX_ATTEMPTS = 3


@dataclass
class ClaimedJob:
    id: int
    user_id: int
    source_id: int
    highlight_id: int | None
    schedule_id: int | None
    attempts: int


@dataclass
class DueSchedule:
    id: int
    user_id: int
    source_id: int
    every_hours: int
    max_shorts: int | None
    produced_count: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TenantStore:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required for TenantStore")
        self.conn = psycopg.connect(database_url)

    def close(self) -> None:
        self.conn.close()

    # --- users -------------------------------------------------------------

    def upsert_user(self, tg_user_id: int, tg_username: str = "") -> int:
        """Возвращает id юзера, заводя его при первом обращении к боту."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (tg_user_id, tg_username)
                     VALUES (%s, %s)
                ON CONFLICT (tg_user_id) DO UPDATE
                        SET tg_username = EXCLUDED.tg_username
                  RETURNING id
                """,
                (tg_user_id, tg_username or None),
            )
            user_id = cur.fetchone()[0]
        self.conn.commit()
        return user_id

    def set_user_status(self, user_id: int, status: str, reason: str = "") -> None:
        """Рубильник на юзера: гасит его, не трогая деплой."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET status = %s, status_reason = %s WHERE id = %s",
                (status, reason or None, user_id),
            )
            # Приостановленный юзер не должен продолжать получать нарезки
            # по ранее заведённым расписаниям.
            if status != "active":
                cur.execute(
                    "UPDATE schedules SET active = false WHERE user_id = %s", (user_id,)
                )
        self.conn.commit()

    def is_active(self, user_id: int) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT status FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return bool(row) and row[0] == "active"

    # --- sources -----------------------------------------------------------

    def create_source(self, user_id: int, storage_key: str, filename: str = "") -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sources (user_id, storage_key, original_filename)
                     VALUES (%s, %s, %s)
                  RETURNING id
                """,
                (user_id, storage_key, filename or None),
            )
            source_id = cur.fetchone()[0]
        self.conn.commit()
        return source_id

    def confirm_rights(self, source_id: int) -> None:
        """Подтверждение прав на контент — конвейер без него не стартует."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE sources SET rights_confirmed_at = now() WHERE id = %s",
                (source_id,),
            )
        self.conn.commit()

    def set_source_status(self, source_id: int, status: str, error: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE sources SET status = %s, error = %s WHERE id = %s",
                (status, error or None, source_id),
            )
        self.conn.commit()

    def set_source_media(
        self, source_id: int, duration_s: int, size_bytes: int = 0
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sources
                   SET duration_s = %s,
                       size_bytes = COALESCE(NULLIF(%s, 0), size_bytes)
                 WHERE id = %s
                """,
                (duration_s, size_bytes, source_id),
            )
        self.conn.commit()

    def is_ready_to_process(self, source_id: int) -> bool:
        """Загружен и права подтверждены — иначе запускать конвейер нельзя."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, rights_confirmed_at IS NOT NULL
                  FROM sources
                 WHERE id = %s
                """,
                (source_id,),
            )
            row = cur.fetchone()
        return bool(row) and row[0] == "uploaded" and row[1]

    # --- transcript --------------------------------------------------------

    def save_transcript(self, source_id: int, segments: list[TranscriptSegment]) -> None:
        """Перезаписывает транскрипт целиком — повторный прогон не должен дублировать."""
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM transcript_segments WHERE source_id = %s", (source_id,)
            )
            if segments:
                cur.executemany(
                    """
                    INSERT INTO transcript_segments (source_id, start_ms, end_ms, text)
                         VALUES (%s, %s, %s, %s)
                    """,
                    [(source_id, s.start_ms, s.end_ms, s.text) for s in segments],
                )
        self.conn.commit()

    def load_transcript(self, source_id: int) -> list[TranscriptSegment]:
        """Сегменты без пословных таймкодов — в схеме их нет.

        Для субтитров нужен полный результат распознавания, поэтому конвейер
        держит его в памяти в рамках прогона, а сюда пишет только текст:
        он нужен для показа юзеру и для повторного отбора хайлайтов.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT start_ms, end_ms, text
                  FROM transcript_segments
                 WHERE source_id = %s
                 ORDER BY start_ms
                """,
                (source_id,),
            )
            rows = cur.fetchall()
        return [
            TranscriptSegment(start_ms=r[0], end_ms=r[1], text=r[2], words=[])
            for r in rows
        ]

    # --- highlights --------------------------------------------------------

    def save_highlights(self, source_id: int, highlights: list[Highlight]) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM highlights WHERE source_id = %s", (source_id,))
            if highlights:
                cur.executemany(
                    """
                    INSERT INTO highlights (source_id, start_ms, end_ms, score, title, reason)
                         VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (source_id, h.start_ms, h.end_ms, h.score, h.title, h.reason)
                        for h in highlights
                    ],
                )
        self.conn.commit()

    def take_next_highlight(self, source_id: int) -> tuple[int, Highlight] | None:
        """Забирает лучший неиспользованный хайлайт и сразу помечает его.

        Пометка в той же транзакции: иначе два одновременных тика планировщика
        выдали бы один и тот же фрагмент дважды.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE highlights
                   SET consumed_at = now()
                 WHERE id = (
                       SELECT id
                         FROM highlights
                        WHERE source_id = %s AND consumed_at IS NULL
                        ORDER BY score DESC
                        LIMIT 1
                          FOR UPDATE SKIP LOCKED
                 )
             RETURNING id, start_ms, end_ms, score, title, reason
                """,
                (source_id,),
            )
            row = cur.fetchone()
        self.conn.commit()
        if row is None:
            return None
        return row[0], Highlight(
            start_ms=row[1], end_ms=row[2], score=float(row[3]),
            title=row[4] or "", reason=row[5] or "",
        )

    # --- schedules ---------------------------------------------------------

    def create_schedule(
        self, user_id: int, source_id: int, every_hours: int, max_shorts: int | None = None
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO schedules (user_id, source_id, every_hours, next_run_at, max_shorts)
                     VALUES (%s, %s, %s, now(), %s)
                  RETURNING id
                """,
                (user_id, source_id, every_hours, max_shorts),
            )
            schedule_id = cur.fetchone()[0]
        self.conn.commit()
        return schedule_id

    def set_cadence(self, schedule_id: int, every_hours: int) -> None:
        """Периодичность живёт строкой в базе: планировщик читает её на каждом тике,
        поэтому изменение применяется сразу и не требует правки чего-либо ещё."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE schedules
                   SET every_hours = %s,
                       next_run_at = now() + make_interval(hours => %s)
                 WHERE id = %s
                """,
                (every_hours, every_hours, schedule_id),
            )
        self.conn.commit()

    def due_schedules(self, limit: int = 50) -> list[DueSchedule]:
        """Созревшие расписания активных юзеров, у которых лимит ещё не выбран."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id, s.user_id, s.source_id, s.every_hours,
                       s.max_shorts, s.produced_count
                  FROM schedules s
                  JOIN users u ON u.id = s.user_id
                 WHERE s.active
                   AND s.next_run_at <= now()
                   AND u.status = 'active'
                   AND (s.max_shorts IS NULL OR s.produced_count < s.max_shorts)
                 ORDER BY s.next_run_at
                 LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [DueSchedule(*row) for row in rows]

    def advance_schedule(self, schedule_id: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE schedules
                   SET next_run_at = now() + make_interval(hours => every_hours),
                       produced_count = produced_count + 1
                 WHERE id = %s
                """,
                (schedule_id,),
            )
            # Лимит выбран — расписание больше не будит планировщик.
            cur.execute(
                """
                UPDATE schedules
                   SET active = false
                 WHERE id = %s
                   AND max_shorts IS NOT NULL
                   AND produced_count >= max_shorts
                """,
                (schedule_id,),
            )
        self.conn.commit()

    # --- jobs --------------------------------------------------------------

    def enqueue_job(
        self,
        user_id: int,
        source_id: int,
        highlight_id: int | None = None,
        schedule_id: int | None = None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (user_id, source_id, highlight_id, schedule_id)
                     VALUES (%s, %s, %s, %s)
                  RETURNING id
                """,
                (user_id, source_id, highlight_id, schedule_id),
            )
            job_id = cur.fetchone()[0]
        self.conn.commit()
        return job_id

    def claim_jobs(self, worker_id: str, limit: int = 1) -> list[ClaimedJob]:
        """Забирает задачи под воркер.

        SKIP LOCKED — то, ради чего это написано: как только воркеров станет
        больше одного (второй процесс, вторая реплика сервиса), без него оба
        возьмут одну задачу и отрендерят один шортс дважды, за счёт клиента.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                   SET state = 'rendering',
                       locked_at = now(),
                       locked_by = %s,
                       attempts = attempts + 1,
                       updated_at = now()
                 WHERE id IN (
                       SELECT id
                         FROM jobs
                        WHERE state = 'pending'
                        ORDER BY created_at
                        LIMIT %s
                          FOR UPDATE SKIP LOCKED
                 )
             RETURNING id, user_id, source_id, highlight_id, schedule_id, attempts
                """,
                (worker_id, limit),
            )
            rows = cur.fetchall()
        self.conn.commit()
        return [ClaimedJob(*row) for row in rows]

    def reclaim_stale_jobs(self, older_than_seconds: int = STALE_LOCK_SECONDS) -> int:
        """Возвращает в очередь задачи мёртвых воркеров.

        Без этого упавший посреди рендера воркер оставлял бы задачу в rendering
        навсегда, и юзер не получил бы ничего и без объяснений.
        """
        cutoff = _utcnow() - timedelta(seconds=older_than_seconds)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                   SET state = CASE WHEN attempts >= %s THEN 'failed' ELSE 'pending' END,
                       error = CASE WHEN attempts >= %s
                                    THEN 'воркер не ответил, попытки исчерпаны'
                                    ELSE error END,
                       locked_at = NULL,
                       locked_by = NULL,
                       updated_at = now()
                 WHERE state = 'rendering'
                   AND locked_at < %s
                """,
                (MAX_ATTEMPTS, MAX_ATTEMPTS, cutoff),
            )
            reclaimed = cur.rowcount
        self.conn.commit()
        return reclaimed

    def finish_job(self, job_id: int, output_key: str, youtube_video_id: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                   SET state = 'done',
                       output_key = %s,
                       youtube_video_id = %s,
                       locked_at = NULL,
                       locked_by = NULL,
                       updated_at = now()
                 WHERE id = %s
                """,
                (output_key, youtube_video_id or None, job_id),
            )
        self.conn.commit()

    def fail_job(self, job_id: int, error: str) -> None:
        """Возвращает задачу в очередь, пока не исчерпаны попытки."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                   SET state = CASE WHEN attempts >= %s THEN 'failed' ELSE 'pending' END,
                       error = %s,
                       locked_at = NULL,
                       locked_by = NULL,
                       updated_at = now()
                 WHERE id = %s
                """,
                (MAX_ATTEMPTS, error[:2000], job_id),
            )
        self.conn.commit()

    # --- audit -------------------------------------------------------------

    def log(
        self,
        action: str,
        user_id: int | None = None,
        entity: str = "",
        entity_id: int | None = None,
        meta: dict | None = None,
    ) -> None:
        """След для ответа на вопрос «что это за видео» — за минуту, а не за неделю."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, entity, entity_id, meta)
                     VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, action, entity or None, entity_id,
                 json.dumps(meta, ensure_ascii=False) if meta else None),
            )
        self.conn.commit()
