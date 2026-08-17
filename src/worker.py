"""Воркер: разбирает очередь ``jobs`` и превращает загруженное видео в шортсы.

Замыкает цепочку. Бот кладёт задачу и сразу отвечает юзеру — вебхук обязан
уложиться в секунды, а нарезка идёт минуты; всё тяжёлое происходит здесь.

Живёт фоновым потоком в том же процессе, что и веб-сервер. Это работает
потому, что ffmpeg запускается через ``nice``: рендер уступает процессор
uvicorn, и бот продолжает отвечать, пока считается нарезка.

Каждый готовый клип уходит юзеру сразу, не дожидаясь остальных: на длинном
исходнике с десятком нарезок разница между «первый ролик через пару минут» и
«тишина полчаса» — это разница между сервисом и подозрением, что всё сломалось.
"""

from __future__ import annotations

import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .bot import BotConfig, load_bot_config
from .notify_telegram import send_files_to_telegram
from .remote_assets import build_s3_client
from .shorts_cut import ShortClip
from .shorts_pipeline import build_shorts
from .tenant_store import ClaimedJob, TenantStore

LOGGER = logging.getLogger("content_factory")

# Пустая очередь — обычное состояние, опрашивать её чаще незачем.
IDLE_SLEEP_SECONDS = 15

# Брошенные задачи подбираем не на каждом тике: это разовая уборка,
# а не часть горячего пути.
RECLAIM_EVERY_SECONDS = 300


@dataclass
class WorkerSettings:
    enabled: bool
    worker_id: str
    whisper_model: str
    whisper_download_root: str
    language: str
    max_shorts: int
    min_seconds: int
    max_seconds: int


def load_worker_settings() -> WorkerSettings:
    return WorkerSettings(
        enabled=os.getenv("SHORTS_WORKER_ENABLED", "").strip().lower() in {"1", "true", "yes"},
        # Имя воркера попадает в jobs.locked_by — по нему видно, кто взял
        # задачу, если она подвиснет.
        worker_id=os.getenv("RAILWAY_REPLICA_ID", "").strip() or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}",
        whisper_model=os.getenv("WHISPER_MODEL", "").strip() or "tiny",
        whisper_download_root=os.getenv("WHISPER_DOWNLOAD_ROOT", "").strip(),
        language=os.getenv("WHISPER_LANGUAGE", "").strip(),
        max_shorts=int(os.getenv("SHORTS_MAX_PER_SOURCE", "5")),
        min_seconds=int(os.getenv("SHORTS_MIN_SECONDS", "20")),
        max_seconds=int(os.getenv("SHORTS_MAX_SECONDS", "60")),
    )


def notify_text(cfg: BotConfig, chat_id: int, text: str) -> None:
    """Текстовое сообщение юзеру.

    ``send_files_to_telegram`` умеет только файлы и при пустом списке молча
    выходит — а объяснить, почему роликов не будет, обязательно: иначе юзер
    видит тишину и считает, что сервис сломался.
    """
    import requests

    try:
        requests.post(
            f"https://api.telegram.org/bot{cfg.token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except requests.RequestException as exc:
        LOGGER.warning("WORKER: не смог отправить сообщение юзеру: %s", exc)


def download_source(cfg: BotConfig, key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = build_s3_client(cfg.s3)
    client.download_file(cfg.s3.bucket, key, str(dest))
    return dest


def _job_context(db: TenantStore, job: ClaimedJob) -> tuple[str, int] | None:
    """Ключ исходника и Telegram-чат юзера — без них задачу выполнять некуда."""
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.storage_key, u.tg_user_id
              FROM sources s
              JOIN users u ON u.id = s.user_id
             WHERE s.id = %s
            """,
            (job.source_id,),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else None


def process_job(
    job: ClaimedJob,
    db: TenantStore,
    cfg: BotConfig,
    settings: WorkerSettings,
) -> int:
    """Обрабатывает одну задачу. Возвращает число отданных клипов."""
    context = _job_context(db, job)
    if context is None:
        db.fail_job(job.id, "исходник или юзер не найдены")
        return 0

    storage_key, tg_chat_id = context
    delivered = 0

    with tempfile.TemporaryDirectory(prefix="shorts_job_") as tmp:
        tmp_dir = Path(tmp)
        source = download_source(cfg, storage_key, tmp_dir / Path(storage_key).name)
        db.set_source_status(job.source_id, "transcribing")

        def deliver(clip: ShortClip) -> None:
            nonlocal delivered
            # Отдаём по мере готовности: если рендер упадёт на пятом ролике,
            # первые четыре у юзера уже будут.
            send_files_to_telegram(
                bot_token=cfg.token,
                chat_id=str(tg_chat_id),
                file_paths=[clip.path],
                caption_prefix="Шортс готов",
            )
            delivered += 1

        result = build_shorts(
            source,
            tmp_dir / "out",
            whisper_model=settings.whisper_model,
            whisper_download_root=settings.whisper_download_root,
            language=settings.language,
            max_count=settings.max_shorts,
            min_seconds=settings.min_seconds,
            max_seconds=settings.max_seconds,
            on_clip_ready=deliver,
        )

        db.set_source_media(job.source_id, result.source_duration_ms // 1000)
        db.save_transcript(job.source_id, result.segments)
        db.save_highlights(job.source_id, result.highlights)

        if not result.had_speech:
            db.set_source_status(job.source_id, "failed", "в видео не найдено речи")
            # Не fail_job: повторять нечего, речь от повторной попытки
            # не появится. Закрываем как выполненную, но без клипов.
            db.finish_job(job.id, output_key="")
            notify_text(
                cfg, tg_chat_id,
                "В этом видео не нашлось речи — нарезать шортсы с субтитрами не из чего. "
                "Пришли видео, где кто-то говорит.",
            )
            return 0

        if delivered == 0:
            notify_text(
                cfg, tg_chat_id,
                "Речь распозналась, но подходящих фрагментов не нашлось. "
                "Обычно так бывает на очень коротких видео — попробуй запись подлиннее.",
            )

        db.set_source_status(job.source_id, "ready")
        db.finish_job(job.id, output_key=f"{storage_key}#shorts")
        db.log(
            "shorts_delivered", user_id=job.user_id, entity="job", entity_id=job.id,
            meta={"clips": delivered, "highlights": len(result.highlights)},
        )

    return delivered


def run_once(cfg: BotConfig, settings: WorkerSettings) -> int:
    """Забирает одну задачу и обрабатывает. Возвращает число отданных клипов."""
    db = TenantStore(cfg.database_url)
    try:
        claimed = db.claim_jobs(settings.worker_id, limit=1)
        if not claimed:
            return 0
        job = claimed[0]
        LOGGER.info("WORKER: взял задачу %s (source %s)", job.id, job.source_id)
        try:
            return process_job(job, db, cfg, settings)
        except Exception as exc:  # noqa: BLE001 — падать целиком воркеру нельзя
            LOGGER.exception("WORKER: задача %s провалилась", job.id)
            db.fail_job(job.id, str(exc))
            db.set_source_status(job.source_id, "failed", str(exc)[:500])
            return 0
    finally:
        db.close()


def run_forever(cfg: BotConfig, settings: WorkerSettings) -> None:
    last_reclaim = 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_reclaim > RECLAIM_EVERY_SECONDS:
                db = TenantStore(cfg.database_url)
                try:
                    reclaimed = db.reclaim_stale_jobs()
                    if reclaimed:
                        LOGGER.info("WORKER: вернул в очередь %s брошенных задач", reclaimed)
                finally:
                    db.close()
                last_reclaim = now

            if run_once(cfg, settings) == 0:
                time.sleep(IDLE_SLEEP_SECONDS)
        except Exception:  # noqa: BLE001
            # Сбой соединения с базой не должен убивать поток целиком:
            # иначе один сетевой глюк останавливает обработку до передеплоя.
            LOGGER.exception("WORKER: тик упал, продолжаю")
            time.sleep(IDLE_SLEEP_SECONDS)


def start_background_worker() -> bool:
    """Поднимает воркер фоновым потоком. False, если он выключен или не настроен."""
    settings = load_worker_settings()
    if not settings.enabled:
        return False
    cfg = load_bot_config()
    if not cfg.configured:
        LOGGER.warning("WORKER: не запущен — нет токена бота или DATABASE_URL")
        return False

    thread = threading.Thread(
        target=run_forever, args=(cfg, settings), name="shorts-worker", daemon=True
    )
    thread.start()
    LOGGER.info("WORKER: запущен как %s", settings.worker_id)
    return True
