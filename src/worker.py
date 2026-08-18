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

import json
import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .bot import (
    BotConfig,
    load_bot_config,
    output_prefix,
    timecode,
    timecode_mark,
    upload_output,
)
from .highlights import Highlight
from .remote_assets import build_s3_client
from .shorts_cut import ShortClip
from .shorts_cut import cut_short
from .shorts_pipeline import (
    DEFAULT_CRF,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_PRESET,
    DEFAULT_WIDTH,
    build_shorts,
)
from .subtitles import build_ass, window_words
from .transcribe import TranscriptSegment, Word
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
        # Веса Whisper весят сотни мегабайт. Без волюма они лягут в
        # эфемерную файловую систему и будут качаться заново после каждого
        # деплоя — это минуты простоя на ровном месте.
        whisper_download_root=(
            os.getenv("WHISPER_DOWNLOAD_ROOT", "").strip()
            or (
                f'{os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()}/whisper'
                if os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
                else ""
            )
        ),
        language=os.getenv("WHISPER_LANGUAGE", "").strip(),
        max_shorts=int(os.getenv("SHORTS_MAX_PER_SOURCE", "5")),
        min_seconds=int(os.getenv("SHORTS_MIN_SECONDS", "20")),
        max_seconds=int(os.getenv("SHORTS_MAX_SECONDS", "60")),
    )


def transcript_key(user_id: int, source_id: int) -> str:
    return f"{output_prefix(user_id, source_id)}transcript.json"


def save_transcript_blob(cfg: BotConfig, job: ClaimedJob, segments) -> None:
    """Кладёт транскрипт с пословными таймкодами рядом с нарезкой.

    В базе хранится только текст: пословные тайминги там не нужны никому,
    кроме субтитров. Но нарезка заказывается позже отдельной задачей, и без
    этого файла пришлось бы распознавать восемьдесят минут заново.
    """
    payload = json.dumps(
        [
            {
                "start_ms": seg.start_ms, "end_ms": seg.end_ms, "text": seg.text,
                "words": [
                    {"start_ms": w.start_ms, "end_ms": w.end_ms, "text": w.text}
                    for w in seg.words
                ],
            }
            for seg in segments
        ],
        ensure_ascii=False,
    ).encode("utf-8")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        handle.write(payload)
        path = Path(handle.name)
    try:
        upload_output(cfg, path, transcript_key(job.user_id, job.source_id))
    finally:
        path.unlink(missing_ok=True)


def load_transcript_blob(cfg: BotConfig, job: ClaimedJob) -> list[TranscriptSegment]:
    """Возвращает сохранённый транскрипт. Пустой список, если его нет."""
    raw = download_bytes(cfg, transcript_key(job.user_id, job.source_id))
    if not raw:
        return []
    return [
        TranscriptSegment(
            start_ms=item["start_ms"], end_ms=item["end_ms"], text=item["text"],
            words=[
                Word(start_ms=w["start_ms"], end_ms=w["end_ms"], text=w["text"])
                for w in item.get("words") or []
            ],
        )
        for item in json.loads(raw.decode("utf-8"))
    ]


def notify_text(cfg: BotConfig, chat_id: int, text: str) -> None:
    """Текстовое сообщение юзеру.

    Объяснить, почему роликов не будет, обязательно: иначе юзер видит тишину
    и считает, что сервис сломался.
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


def clip_caption(highlight: Highlight, index: int) -> str:
    """Подпись к ролику: откуда вырезано, о чём и почему выбрано.

    Без таймкода юзер не может ни проверить выбор, ни вернуться к этому месту
    в исходнике; без обоснования — не понимает логику отбора и не может
    сказать нам, где она промахивается.
    """
    span = f"{timecode(highlight.start_ms)}–{timecode(highlight.end_ms)}"
    seconds = highlight.duration_ms // 1000
    parts = [f"#{index} · {span} ({seconds} с)"]
    if highlight.title:
        parts.append(highlight.title)
    if highlight.reason:
        parts.append(highlight.reason)
    return "\n".join(parts)


def send_clip(cfg: BotConfig, chat_id: int, path: Path, caption: str) -> None:
    """Отправляет ролик как видео, а не документ — так он играет прямо в чате.

    Своя отправка, а не notify_telegram: тот шлёт документом и приписывает к
    подписи «clip 1/1», что для одиночного ролика выглядит мусором.
    """
    import requests

    try:
        with path.open("rb") as handle:
            requests.post(
                f"https://api.telegram.org/bot{cfg.token}/sendVideo",
                data={"chat_id": chat_id, "caption": caption[:1024], "supports_streaming": "true"},
                files={"video": (path.name, handle, "video/mp4")},
                timeout=300,
            )
    except requests.RequestException as exc:
        LOGGER.warning("WORKER: не смог отправить ролик: %s", exc)


def download_bytes(cfg: BotConfig, key: str) -> bytes:
    client = build_s3_client(cfg.s3)
    try:
        return client.get_object(Bucket=cfg.bucket_for_uploads, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001
        return b""


def download_source(cfg: BotConfig, key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = build_s3_client(cfg.s3)
    client.download_file(cfg.bucket_for_uploads, key, str(dest))
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


def send_choice_list(
    cfg: BotConfig, chat_id: int, source_id: int,
    stored: list[tuple[int, Highlight]], duration_ms: int,
) -> None:
    """Присылает найденные фрагменты кнопками — резать будем только выбранные.

    Рендер самая тяжёлая часть прохода, и тратить его на ролики, которые юзер
    не заказывал, незачем: на полуторачасовом исходнике это десятки минут
    процессорного времени впустую.
    """
    import requests

    lines = [f"Нашёл {len(stored)} фрагментов в {duration_ms // 60000} мин:"]
    keyboard = []
    for index, (highlight_id, highlight) in enumerate(stored, start=1):
        span = f"{timecode(highlight.start_ms)}–{timecode(highlight.end_ms)}"
        lines.append(f"\n{index}. {span} · {highlight.title}")
        if highlight.reason:
            lines.append(f"   {highlight.reason}")
        keyboard.append([{
            "text": f"{index}. {span} · {highlight.title}"[:60],
            "callback_data": f"cut:{source_id}:{highlight_id}",
        }])

    try:
        requests.post(
            f"https://api.telegram.org/bot{cfg.token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "\n".join(lines)[:4000],
                "reply_markup": {"inline_keyboard": keyboard},
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        LOGGER.warning("WORKER: не смог отправить список фрагментов: %s", exc)


def analyze_source(
    job: ClaimedJob, db: TenantStore, cfg: BotConfig,
    settings: WorkerSettings, storage_key: str, tg_chat_id: int,
) -> int:
    """Распознаёт речь и отбирает фрагменты, ничего не нарезая."""
    with tempfile.TemporaryDirectory(prefix="shorts_scan_") as tmp:
        tmp_dir = Path(tmp)
        LOGGER.info("WORKER: качаю исходник %s", storage_key)
        source = download_source(cfg, storage_key, tmp_dir / Path(storage_key).name)
        LOGGER.info(
            "WORKER: исходник на месте, %.0f МБ — распознаю речь",
            source.stat().st_size / 1048576,
        )
        db.set_source_status(job.source_id, "transcribing")

        result = build_shorts(
            source, tmp_dir / "out",
            whisper_model=settings.whisper_model,
            whisper_download_root=settings.whisper_download_root,
            language=settings.language,
            max_count=settings.max_shorts,
            min_seconds=settings.min_seconds,
            max_seconds=settings.max_seconds,
            # Ничего не режем: юзер сначала смотрит список.
            render=False,
        )

    LOGGER.info(
        "WORKER: речь %s, фрагментов отобрано %s",
        "найдена" if result.had_speech else "не найдена", len(result.highlights),
    )
    db.set_source_media(job.source_id, result.source_duration_ms // 1000)
    db.save_transcript(job.source_id, result.segments)

    if not result.had_speech:
        db.set_source_status(job.source_id, "failed", "в видео не найдено речи")
        db.finish_job(job.id, output_key="")
        notify_text(
            cfg, tg_chat_id,
            "В этом видео не нашлось речи — нарезать шортсы с субтитрами не из чего. "
            "Пришли видео, где кто-то говорит.",
        )
        return 0

    save_transcript_blob(cfg, job, result.segments)
    stored = db.save_highlights_returning_ids(job.source_id, result.highlights)

    if not stored:
        db.set_source_status(job.source_id, "ready")
        db.finish_job(job.id, output_key="")
        notify_text(
            cfg, tg_chat_id,
            "Речь распозналась, но подходящих фрагментов не нашлось. "
            "Обычно так бывает на очень коротких видео — попробуй запись подлиннее.",
        )
        return 0

    send_choice_list(cfg, tg_chat_id, job.source_id, stored, result.source_duration_ms)
    db.set_source_status(job.source_id, "ready")
    db.finish_job(job.id, output_key="")
    db.log("source_analyzed", user_id=job.user_id, entity="source",
           entity_id=job.source_id, meta={"highlights": len(stored)})
    return 0


def render_one(
    job: ClaimedJob, db: TenantStore, cfg: BotConfig,
    settings: WorkerSettings, storage_key: str, tg_chat_id: int,
) -> int:
    """Режет один заказанный фрагмент."""
    highlight = db.highlight_by_id(job.highlight_id, job.source_id)
    if highlight is None:
        db.fail_job(job.id, "фрагмент не найден")
        return 0

    segments = load_transcript_blob(cfg, job)
    words = [w for seg in segments for w in seg.words]

    with tempfile.TemporaryDirectory(prefix="shorts_cut_") as tmp:
        tmp_dir = Path(tmp)
        source = download_source(cfg, storage_key, tmp_dir / Path(storage_key).name)

        ass_text = ""
        clip_words = window_words(words, highlight.start_ms, highlight.end_ms)
        if clip_words:
            ass_text = build_ass(clip_words, DEFAULT_WIDTH, DEFAULT_HEIGHT)
        elif not words:
            # Транскрипт не нашёлся — режем без субтитров, но говорим об этом.
            LOGGER.warning("WORKER: транскрипт недоступен, режу без субтитров")

        mark = timecode_mark(highlight.start_ms)
        clip = cut_short(
            source_path=source,
            output_path=tmp_dir / f"short_{mark}.mp4",
            start_ms=highlight.start_ms, end_ms=highlight.end_ms,
            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS,
            encode_preset=DEFAULT_PRESET, crf=DEFAULT_CRF,
            ass_text=ass_text,
        )
        LOGGER.info(
            "WORKER: готов ролик %s-%s",
            timecode(highlight.start_ms), timecode(highlight.end_ms),
        )

        key = f"{output_prefix(job.user_id, job.source_id)}{mark}.mp4"
        upload_output(cfg, clip.path, key)
        send_clip(cfg, tg_chat_id, clip.path, clip_caption(highlight, 1))

    db.finish_job(job.id, output_key=key)
    db.log("clip_rendered", user_id=job.user_id, entity="highlight",
           entity_id=job.highlight_id, meta={"key": key})
    return 1


def process_job(
    job: ClaimedJob,
    db: TenantStore,
    cfg: BotConfig,
    settings: WorkerSettings,
) -> int:
    """Обрабатывает одну задачу.

    Задача без ``highlight_id`` — это разбор исходника: распознать речь,
    отобрать фрагменты и показать их юзеру. С ``highlight_id`` — нарезка
    одного заказанного фрагмента.
    """
    context = _job_context(db, job)
    if context is None:
        db.fail_job(job.id, "исходник или юзер не найдены")
        return 0

    storage_key, tg_chat_id = context
    if job.highlight_id is None:
        return analyze_source(job, db, cfg, settings, storage_key, tg_chat_id)
    return render_one(job, db, cfg, settings, storage_key, tg_chat_id)


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
