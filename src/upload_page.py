"""Страница загрузки файла — то, что юзер открывает по ссылке из бота.

Presigned-ссылка подписана под PUT, поэтому в браузере она не открывается:
браузер делает GET, подпись не совпадает, и R2 отдаёт простыню XML. Юзер
читает её как поломку сервиса.

Поэтому бот присылает адрес этой страницы, а не саму presigned-ссылку.
Страница отдаёт форму, а PUT делает уже javascript — с прогрессом, потому что
на гигабайтном файле полоска это разница между «работает» и «завис».

Ссылка выписывается на открытии страницы, а не при выдаче: иначе к моменту,
когда юзер соберётся загружать, шесть часов могли уже истечь.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .bot import BotConfig, load_bot_config, presigned_upload_url
from .remote_assets import build_s3_client
from .tenant_store import TenantStore

LOGGER = logging.getLogger("content_factory")

UPLOAD_PATH = "/upload/{token}"

_BROKEN = """<!doctype html>
<html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Загрузка недоступна</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:34rem;margin:0 auto;
  padding:2rem 1.25rem}}code{{background:#8883;padding:.1em .35em;border-radius:.25em}}</style>
<h1>Загрузка пока недоступна</h1>
<p>{reason}</p>
<p>Это неполадка на нашей стороне — файл тут ни при чём. Напиши в поддержку.</p>
</html>"""

_PAGE = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Загрузка видео</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 system-ui, -apple-system, sans-serif; max-width: 34rem;
         margin: 0 auto; padding: 2rem 1.25rem; }}
  h1 {{ font-size: 1.35rem; margin: 0 0 .25rem; }}
  p.sub {{ margin: 0 0 1.75rem; opacity: .7; }}
  label {{ display: block; border: 2px dashed currentColor; border-radius: .75rem;
           padding: 2rem 1rem; text-align: center; cursor: pointer; opacity: .75; }}
  label:hover {{ opacity: 1; }}
  input[type=file] {{ display: none; }}
  progress {{ width: 100%; height: 1.25rem; margin-top: 1.25rem; display: none; }}
  #msg {{ margin-top: 1rem; min-height: 1.5rem; }}
  .ok {{ color: #15803d; font-weight: 600; }}
  .err {{ color: #b91c1c; font-weight: 600; }}
</style>
<h1>Загрузка видео</h1>
<p class="sub">Выбери файл — он уйдёт напрямую в хранилище. Вкладку не закрывай.</p>

<label for="f" id="drop">Нажми, чтобы выбрать видео</label>
<input type="file" id="f" accept="video/*">
<progress id="bar" max="100" value="0"></progress>
<div id="msg"></div>

<script>
const url = {url!r};
const f = document.getElementById('f');
const bar = document.getElementById('bar');
const msg = document.getElementById('msg');
const drop = document.getElementById('drop');

f.addEventListener('change', () => {{
  const file = f.files[0];
  if (!file) return;
  drop.textContent = file.name + ' — ' + (file.size / 1048576).toFixed(0) + ' МБ';
  bar.style.display = 'block';
  msg.textContent = 'Загружаю…';
  msg.className = '';

  // XHR, а не fetch: нужен onprogress, у fetch его для отправки нет.
  const xhr = new XMLHttpRequest();
  xhr.open('PUT', url, true);
  xhr.upload.onprogress = e => {{
    if (e.lengthComputable) bar.value = (e.loaded / e.total) * 100;
  }};
  xhr.onload = () => {{
    if (xhr.status >= 200 && xhr.status < 300) {{
      msg.textContent = 'Готово. Вернись в Telegram и нажми «Файл загружен».';
      msg.className = 'ok';
    }} else {{
      msg.textContent = 'Хранилище отказало: ' + xhr.status;
      msg.className = 'err';
    }}
  }};
  xhr.onerror = () => {{
    msg.textContent = 'Сеть оборвалась. Обнови страницу и попробуй снова.';
    msg.className = 'err';
  }};
  xhr.send(file);
}});
</script>
</html>"""


def find_storage_key(cfg: BotConfig, token: str) -> str:
    """Ключ объекта по токену из ссылки.

    Токен — это случайный сегмент внутри самого ключа, поэтому отдельная
    колонка не нужна, а угадать чужую загрузку нельзя.
    """
    db = TenantStore(cfg.database_url)
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                "SELECT storage_key FROM sources WHERE storage_key LIKE %s LIMIT 1",
                (f"%/{token}/%",),
            )
            row = cur.fetchone()
    finally:
        db.close()
    return row[0] if row else ""


def storage_problem(cfg: BotConfig) -> str:
    """Пустая строка, если в бакет реально можно загружать.

    Проверяем и существование, и CORS: без политики браузер не отправит PUT,
    а сообщить об этом сам он не может — для него это просто отказ сети.
    """
    client = build_s3_client(cfg.s3)
    bucket = cfg.bucket_for_uploads
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:  # noqa: BLE001
        return f"Хранилище «{bucket}» не найдено."

    try:
        rules = client.get_bucket_cors(Bucket=bucket).get("CORSRules") or []
    except Exception as exc:  # noqa: BLE001
        # Токену может не хватать прав на чтение политики — это не значит,
        # что её нет. Блокировать здесь означало бы перекрыть работающую
        # загрузку из-за нехватки прав у проверяющего, а не у загружающего.
        if "AccessDenied" in str(exc):
            LOGGER.info("UPLOAD PAGE: CORS не проверить — нет прав на чтение политики")
            return ""
        return "У хранилища не настроены правила доступа из браузера (CORS)."

    if not any("PUT" in (r.get("AllowedMethods") or []) for r in rules):
        return "Правила доступа хранилища не разрешают загрузку из браузера."
    return ""


def attach_upload_page(app, cfg: BotConfig | None = None) -> bool:
    """Вешает страницу загрузки на приложение. False, если бот не настроен."""
    cfg = cfg or load_bot_config()
    if not cfg.configured:
        return False

    @app.get(UPLOAD_PATH, response_class=HTMLResponse)
    async def upload_page(token: str) -> HTMLResponse:
        # Токен из ключа — 32 hex-символа; всё остальное даже не ищем в базе.
        if len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
            raise HTTPException(status_code=404, detail="not found")

        key = find_storage_key(cfg, token)
        if not key:
            raise HTTPException(status_code=404, detail="not found")

        # Проверяем хранилище до того, как юзер начнёт заливать гигабайты.
        # Браузер блокирует ответы R2 по CORS, поэтому и отсутствие бакета, и
        # отсутствие политики выглядят на странице одинаково — как обрыв сети.
        # Без этой проверки юзер отправляет полтора гигабайта в стену и не
        # получает ни одной подсказки, что пошло не так.
        broken = storage_problem(cfg)
        if broken:
            LOGGER.error("UPLOAD PAGE: хранилище не готово — %s", broken)
            return HTMLResponse(_BROKEN.format(reason=broken), status_code=503)

        try:
            url = presigned_upload_url(cfg, key)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("UPLOAD PAGE: presigned url failed")
            raise HTTPException(status_code=500, detail=str(exc))

        return HTMLResponse(_PAGE.format(url=url))

    return True
