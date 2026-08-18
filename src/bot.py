"""Telegram-бот: приём длинного видео и выдача нарезки.

Работает на вебхуке, а не на поллинге: публичный домен у сервиса уже есть,
а поллинг молотил бы CPU круглосуточно рядом с рендером.

Файл принимается не через Telegram, а по presigned-ссылке в R2 напрямую:
Bot API отдаёт боту файлы только до 20 МБ, а лонги весят гигабайты.

Вебхук обязан отвечать за секунды, поэтому здесь не запускается ничего
тяжёлого — бот пишет строки в базу и отвечает. Нарезкой занимается воркер,
разбирающий очередь ``jobs``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass

# На уровне модуля, а не внутри attach_webhook: из-за
# ``from __future__ import annotations`` аннотации роута — строки, и FastAPI
# разрешает их по пространству имён модуля.
from fastapi import Header, HTTPException, Request

from .remote_assets import S3SyncConfig, build_s3_client
from .tenant_store import TenantStore

LOGGER = logging.getLogger("content_factory")

WEBHOOK_PATH = "/telegram/webhook"

# Заголовок, которым Telegram подписывает свои запросы. Без сверки вебхук
# принимал бы поддельные апдейты от кого угодно, кто узнал адрес.
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

UPLOAD_URL_TTL_SECONDS = 6 * 3600

MIN_CADENCE_HOURS = 1
MAX_CADENCE_HOURS = 24 * 7

WELCOME = (
    "Пришлю нарезку шортсов из твоего длинного видео.\n\n"
    "Как это работает:\n"
    "1. /upload — дам ссылку для загрузки\n"
    "2. загружаешь файл по ссылке\n"
    "3. подтверждаешь, что видео твоё\n"
    "4. присылаю готовые вертикальные ролики с субтитрами\n\n"
    "Загружать можно только свой контент или тот, на который есть лицензия."
)


@dataclass(frozen=True)
class BotConfig:
    token: str
    database_url: str
    webhook_secret: str
    public_base_url: str
    admin_chat_id: str
    s3: S3SyncConfig
    # Загрузки юзеров держим отдельно от ассетов лофи-конвейера: чужой
    # контент и свои треки не должны жить в одном бакете — разные права
    # доступа, разный жизненный цикл, разная ответственность при инциденте.
    uploads_bucket: str = ""
    upload_prefix: str = "uploads"

    @property
    def bucket_for_uploads(self) -> str:
        return self.uploads_bucket or self.s3.bucket

    @property
    def configured(self) -> bool:
        return bool(self.token and self.database_url)


def load_bot_config() -> BotConfig:
    return BotConfig(
        token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        # Пустой секрет означает, что вебхук никем не подписан — тогда
        # принимать апдейты небезопасно, см. verify_secret.
        webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip(),
        # RAILWAY_PUBLIC_DOMAIN Railway подставляет сам — это и есть адрес,
        # по которому юзер откроет страницу загрузки.
        public_base_url=(
            os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
            or (
                f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()}"
                if os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
                else ""
            )
        ),
        admin_chat_id=os.getenv("ADMIN_CHAT_ID", "").strip(),
        uploads_bucket=os.getenv("UPLOADS_S3_BUCKET", "").strip(),
        s3=S3SyncConfig(
            enabled=True,
            bucket=os.getenv("ASSETS_S3_BUCKET", "").strip(),
            endpoint_url=os.getenv("ASSETS_S3_ENDPOINT_URL", "").strip(),
            region=os.getenv("ASSETS_S3_REGION", "auto").strip(),
            access_key_id=os.getenv("ASSETS_S3_ACCESS_KEY_ID", "").strip(),
            secret_access_key=os.getenv("ASSETS_S3_SECRET_ACCESS_KEY", "").strip(),
            videos_prefix=os.getenv("ASSETS_S3_VIDEOS_PREFIX", "source_videos").strip(),
            tracks_prefix=os.getenv("ASSETS_S3_TRACKS_PREFIX", "tracks").strip(),
        ),
    )


def verify_secret(cfg: BotConfig, header_value: str) -> bool:
    """Апдейт принимается, только если подписан нашим секретом.

    Незаданный секрет — не повод пропускать всё подряд: адрес вебхука
    угадывается, и без сверки любой мог бы слать боту команды от чужого имени.
    """
    if not cfg.webhook_secret:
        return False
    return header_value == cfg.webhook_secret


def upload_key(cfg: BotConfig, user_id: int, filename: str) -> str:
    """Ключ объекта в бакете. Случайный сегмент — чтобы ссылку нельзя было
    угадать и перезаписать чужую загрузку.

    Имя приходит от юзера, поэтому от него остаются только буквы, цифры и
    ``._-``: слеши вырезаются, так что выйти из своего каталога нельзя.
    Подряд идущие точки схлопываются — сами по себе они не опасны, но плодят
    имена вида ``....etcpasswd``, на которых спотыкается сторонний софт.
    """
    kept = "".join(c for c in filename if c.isalnum() or c in "._-")
    while ".." in kept:
        kept = kept.replace("..", ".")
    safe = kept.strip("._-")[-64:] or "video.mp4"
    return f"{cfg.upload_prefix}/{user_id}/{uuid.uuid4().hex}/{safe}"


def upload_token(key: str) -> str:
    """Случайный сегмент ключа. Он же токен страницы загрузки — отдельную
    колонку заводить не нужно, а угадать чужую загрузку нельзя."""
    parts = key.split("/")
    return parts[2] if len(parts) > 2 else ""


def presigned_upload_url(cfg: BotConfig, key: str) -> str:
    client = build_s3_client(cfg.s3)
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": cfg.bucket_for_uploads, "Key": key},
        ExpiresIn=UPLOAD_URL_TTL_SECONDS,
    )


def object_size(cfg: BotConfig, key: str) -> int:
    """Размер загруженного объекта, 0 если его нет.

    Нужно, чтобы не ставить в очередь задачи на файлы, которые юзер так и не
    загрузил: иначе воркер возьмёт задачу и упадёт на отсутствующем исходнике.
    """
    client = build_s3_client(cfg.s3)
    try:
        return int(
            client.head_object(Bucket=cfg.bucket_for_uploads, Key=key)["ContentLength"]
        )
    except Exception:  # noqa: BLE001 — botocore бросает ClientError и его подвиды
        return 0


OUTPUT_PREFIX = "outputs"

DOWNLOAD_URL_TTL_SECONDS = 24 * 3600


def output_prefix(user_id: int, source_id: int) -> str:
    """Куда воркер складывает готовые ролики этой загрузки.

    Ключ выводится из идентификаторов, поэтому список клипов получается
    перечислением префикса — отдельная таблица и миграция под это не нужны.
    """
    return f"{OUTPUT_PREFIX}/{user_id}/{source_id}/"


def presigned_download_url(cfg: BotConfig, key: str) -> str:
    client = build_s3_client(cfg.s3)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": cfg.bucket_for_uploads, "Key": key},
        ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
    )


def list_outputs(cfg: BotConfig, user_id: int, source_id: int) -> list[str]:
    """Ключи готовых роликов по порядку. Пустой список, если их ещё нет."""
    client = build_s3_client(cfg.s3)
    try:
        response = client.list_objects_v2(
            Bucket=cfg.bucket_for_uploads, Prefix=output_prefix(user_id, source_id)
        )
    except Exception:  # noqa: BLE001
        LOGGER.exception("не смог перечислить готовые ролики")
        return []
    return sorted(obj["Key"] for obj in response.get("Contents") or [])


def upload_output(cfg: BotConfig, path, key: str) -> bool:
    client = build_s3_client(cfg.s3)
    try:
        client.upload_file(str(path), cfg.bucket_for_uploads, key)
    except Exception:  # noqa: BLE001
        LOGGER.exception("не смог загрузить готовый ролик %s", key)
        return False
    return True


def delete_object(cfg: BotConfig, key: str) -> bool:
    """Удаляет исходник из хранилища. True, если объекта больше нет.

    Чужое видео не должно лежать у нас дольше, чем нужно: это и деньги за
    хранение, и лишняя ответственность при любом разбирательстве.
    """
    client = build_s3_client(cfg.s3)
    try:
        client.delete_object(Bucket=cfg.bucket_for_uploads, Key=key)
    except Exception:  # noqa: BLE001
        LOGGER.exception("не удалось удалить объект %s", key)
        return False
    return True


def parse_cadence(text: str) -> int | None:
    """Разбирает «24», «24ч», «раз в 24 часа» — юзеры пишут по-разному."""
    digits = "".join(c for c in text if c.isdigit())
    if not digits:
        return None
    try:
        hours = int(digits)
    except ValueError:
        return None
    if not MIN_CADENCE_HOURS <= hours <= MAX_CADENCE_HOURS:
        return None
    return hours


def attach_webhook(app, cfg: BotConfig | None = None) -> bool:
    """Вешает роут вебхука на уже существующее приложение.

    Бот живёт в том же процессе, что и триггер-сервер: у сервиса один порт и
    один публичный домен. Возвращает False, если бот не настроен, — тогда
    лофи-конвейер работает как раньше, ничего не подключая.
    """
    cfg = cfg or load_bot_config()
    if not cfg.configured:
        return False

    from aiogram import Bot
    from aiogram.types import Update

    bot = Bot(token=cfg.token)
    dp = build_dispatcher(cfg)

    @app.post(WEBHOOK_PATH)
    async def telegram_webhook(
        request: Request,
        secret: str = Header(default="", alias=SECRET_HEADER),
    ) -> dict:
        if not verify_secret(cfg, secret):
            raise HTTPException(status_code=403, detail="bad webhook secret")
        update = Update.model_validate(await request.json(), context={"bot": bot})
        # Telegram ретраит апдейт, если не ответить быстро, поэтому обработка
        # обязана оставаться лёгкой: пишем в базу и отвечаем.
        await dp.feed_update(bot, update)
        return {"ok": True}

    return True


def build_dispatcher(cfg: BotConfig):
    """Собирает aiogram-диспетчер. Импорт внутри — чтобы модуль грузился
    в окружениях без aiogram (тесты конфига, лофи-конвейер)."""
    from aiogram import Dispatcher, F
    from aiogram.filters import Command
    from aiogram.types import (
        CallbackQuery,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Message,
    )

    dp = Dispatcher()

    def store() -> TenantStore:
        return TenantStore(cfg.database_url)

    async def in_db(fn, *args, **kwargs):
        """Поход в базу уводим в поток: psycopg синхронный, а блокировать
        цикл событий нельзя — вебхук должен отвечать быстро."""
        def call():
            db = store()
            try:
                return fn(db, *args, **kwargs)
            finally:
                db.close()
        return await asyncio.to_thread(call)

    @dp.message(Command("start"))
    async def on_start(message: Message) -> None:
        await in_db(
            lambda db: db.upsert_user(message.from_user.id, message.from_user.username or "")
        )
        await message.answer(WELCOME)

    @dp.message(Command("upload"))
    async def on_upload(message: Message) -> None:
        user_id = await in_db(
            lambda db: db.upsert_user(message.from_user.id, message.from_user.username or "")
        )
        if not await in_db(lambda db: db.is_active(user_id)):
            await message.answer("Аккаунт приостановлен. Напиши в поддержку.")
            return

        if not cfg.public_base_url:
            await message.answer("Сервис не знает своего публичного адреса — напиши в поддержку.")
            return

        key = upload_key(cfg, user_id, "video.mp4")
        source_id = await in_db(lambda db: db.create_source(user_id, key))

        # Даём адрес страницы, а не presigned-ссылку: она подписана под PUT,
        # и по клику браузер получил бы ошибку подписи вместо формы.
        page_url = f"{cfg.public_base_url}/upload/{upload_token(key)}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="Открыть загрузку", url=page_url)
            ], [
                InlineKeyboardButton(
                    text="Это мой контент", callback_data=f"rights:{source_id}"
                )
            ]]
        )
        await message.answer(
            "Открой страницу загрузки и выбери видео. Когда закончится — "
            "вернись сюда и подтверди права на контент.",
            reply_markup=keyboard,
        )

    @dp.callback_query(F.data.startswith("rights:"))
    async def on_rights(callback: CallbackQuery) -> None:
        source_id = int(callback.data.split(":", 1)[1])
        await in_db(lambda db: db.confirm_rights(source_id))
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="Файл загружен", callback_data=f"uploaded:{source_id}"
                )
            ]]
        )
        await callback.message.answer(
            "Права подтверждены. Как закончишь загрузку — нажми кнопку.",
            reply_markup=keyboard,
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("uploaded:"))
    async def on_uploaded(callback: CallbackQuery) -> None:
        source_id = int(callback.data.split(":", 1)[1])

        def fetch(db: TenantStore):
            with db.conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, storage_key FROM sources WHERE id = %s", (source_id,)
                )
                return cur.fetchone()

        row = await in_db(fetch)
        if row is None:
            await callback.answer("Загрузка не найдена", show_alert=True)
            return

        user_id, key = row
        size = await asyncio.to_thread(object_size, cfg, key)
        if size <= 0:
            await callback.answer(
                "Файла в хранилище нет — загрузка не дошла", show_alert=True
            )
            return

        await in_db(lambda db: db.set_source_status(source_id, "uploaded"))
        await in_db(lambda db: db.set_source_media(source_id, 0, size))
        job_id = await in_db(lambda db: db.enqueue_job(user_id, source_id))
        await in_db(
            lambda db: db.log(
                "source_uploaded", user_id=user_id, entity="source",
                entity_id=source_id, meta={"size_bytes": size, "job_id": job_id},
            )
        )
        await callback.message.answer(
            f"Принято, {size / 1024 / 1024:.0f} МБ. Поставил в очередь — "
            "пришлю ролики по мере готовности."
        )
        await callback.answer()

    @dp.message(Command("status"))
    async def on_status(message: Message) -> None:
        user_id = await in_db(
            lambda db: db.upsert_user(message.from_user.id, message.from_user.username or "")
        )

        def fetch(db: TenantStore):
            with db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.status, s.duration_s,
                           count(j.id) FILTER (WHERE j.state = 'done')
                      FROM sources s
                      LEFT JOIN jobs j ON j.source_id = s.id
                     WHERE s.user_id = %s AND s.status <> 'deleted'
                     GROUP BY s.id
                     ORDER BY s.created_at DESC
                     LIMIT 5
                    """,
                    (user_id,),
                )
                return cur.fetchall()

        rows = await in_db(fetch)
        if not rows:
            await message.answer("Загрузок пока нет. Начни с /upload.")
            return

        for source_id, status, duration_s, done in rows:
            length = f", {duration_s // 60} мин" if duration_s else ""
            await message.answer(
                f"Загрузка #{source_id} — {status}{length}, готовых роликов: {done}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="Нарезать заново", callback_data=f"redo:{source_id}"
                    ),
                    InlineKeyboardButton(
                        text="Скачать оригиналы", callback_data=f"dl:{source_id}"
                    ),
                ], [
                    InlineKeyboardButton(
                        text="Удалить", callback_data=f"del:{source_id}"
                    ),
                ]]),
            )

    async def _owned_source(callback: CallbackQuery, source_id: int):
        """Ключ исходника, если он принадлежит нажавшему кнопку.

        callback_data приходит от клиента, а значит идентификатор в ней можно
        подставить любой — без проверки владельца чужую загрузку удалили бы
        по одной подделанной кнопке.
        """
        user_id = await in_db(
            lambda db: db.upsert_user(callback.from_user.id, callback.from_user.username or "")
        )
        found = await in_db(lambda db: db.source_for_user(source_id, user_id))
        if found is None:
            await callback.answer("Загрузка не найдена", show_alert=True)
            return None, None
        return user_id, found[0]

    @dp.callback_query(F.data.startswith("redo:"))
    async def on_redo(callback: CallbackQuery) -> None:
        source_id = int(callback.data.split(":", 1)[1])
        user_id, key = await _owned_source(callback, source_id)
        if key is None:
            return

        # Файл могли удалить раньше: без проверки воркер взял бы задачу
        # и упал на отсутствующем исходнике.
        if await asyncio.to_thread(object_size, cfg, key) <= 0:
            await callback.answer("Файла в хранилище больше нет", show_alert=True)
            return

        await in_db(lambda db: db.reset_for_rerun(source_id))
        job_id = await in_db(lambda db: db.enqueue_job(user_id, source_id))
        await in_db(
            lambda db: db.log("source_rerun", user_id=user_id, entity="source",
                              entity_id=source_id, meta={"job_id": job_id})
        )
        await callback.message.answer(
            f"Поставил #{source_id} в очередь заново — пришлю новые ролики."
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("dl:"))
    async def on_download(callback: CallbackQuery) -> None:
        source_id = int(callback.data.split(":", 1)[1])
        user_id, key = await _owned_source(callback, source_id)
        if key is None:
            return

        keys = await asyncio.to_thread(list_outputs, cfg, user_id, source_id)
        if not keys:
            await callback.answer("Готовых роликов пока нет", show_alert=True)
            return

        # Ссылки выписываем в момент нажатия: выданные заранее протухли бы
        # раньше, чем юзер до них добрался.
        links = []
        for index, obj_key in enumerate(keys, start=1):
            url = await asyncio.to_thread(presigned_download_url, cfg, obj_key)
            links.append(f"{index}. {obj_key.rsplit('/', 1)[-1]}\n{url}")

        await callback.message.answer(
            "Оригиналы без сжатия Telegram, ссылки действуют сутки:\n\n"
            + "\n\n".join(links),
            disable_web_page_preview=True,
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("del:"))
    async def on_delete(callback: CallbackQuery) -> None:
        source_id = int(callback.data.split(":", 1)[1])
        user_id, key = await _owned_source(callback, source_id)
        if key is None:
            return

        removed = await asyncio.to_thread(delete_object, cfg, key)
        # Вместе с исходником убираем и нарезку: иначе она осталась бы
        # висеть в хранилище, за которое платим, без всякой связи с юзером.
        for out_key in await asyncio.to_thread(list_outputs, cfg, user_id, source_id):
            await asyncio.to_thread(delete_object, cfg, out_key)
        await in_db(lambda db: db.mark_source_deleted(source_id))
        await in_db(
            lambda db: db.log("source_deleted", user_id=user_id, entity="source",
                              entity_id=source_id, meta={"removed": removed})
        )
        await callback.message.answer(
            f"Удалил #{source_id} из хранилища."
            if removed else
            f"Пометил #{source_id} удалённой, но файл убрать не вышло — разберусь."
        )
        await callback.answer()

    return dp
