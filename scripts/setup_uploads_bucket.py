"""Заводит бакет под загрузки юзеров и разрешает браузеру писать в него.

Отдельный бакет, а не общий с ассетами лофи-конвейера: там лежит чужой
контент, у него другой жизненный цикл и другая ответственность при инциденте.
Смешивать их — значит однажды удалить не то.

CORS обязателен: страница загрузки отдаётся с домена сервиса, а PUT уходит на
R2, то есть для браузера это межсайтовый запрос. Без политики он блокируется
ещё до отправки, и XHR сообщает об этом как об обрыве сети — прогресс стоит на
нуле, HTTP-статуса нет. Через curl та же ссылка работает: CORS ограничивает
браузер, а не хранилище.

    python scripts/setup_uploads_bucket.py          # создать и настроить
    python scripts/setup_uploads_bucket.py --show   # показать текущее состояние
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bot import load_bot_config  # noqa: E402
from src.remote_assets import build_s3_client  # noqa: E402


def allowed_origins() -> list[str]:
    origins = []
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        origins.append(f"https://{domain}")
    extra = os.getenv("UPLOAD_ALLOWED_ORIGINS", "").strip()
    origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins


def main() -> int:
    cfg = load_bot_config()
    bucket = cfg.bucket_for_uploads
    if not bucket:
        print("бакет для загрузок не задан (UPLOADS_S3_BUCKET)")
        return 1

    client = build_s3_client(cfg.s3)
    print(f"бакет: {bucket}")

    if "--show" in sys.argv:
        try:
            client.head_bucket(Bucket=bucket)
            print("  существует: да")
        except Exception as exc:  # noqa: BLE001
            print(f"  существует: нет ({exc})")
            return 1
        try:
            for rule in client.get_bucket_cors(Bucket=bucket)["CORSRules"]:
                print(f"  CORS: {rule}")
        except Exception as exc:  # noqa: BLE001
            print(f"  CORS: не настроен ({exc})")
        return 0

    try:
        client.head_bucket(Bucket=bucket)
        print("  уже существует")
    except Exception:  # noqa: BLE001 — botocore бросает ClientError и подвиды
        client.create_bucket(Bucket=bucket)
        print("  создан")

    origins = allowed_origins()
    if not origins:
        print("  CORS пропущен: нет RAILWAY_PUBLIC_DOMAIN")
        return 1

    client.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": origins,
                    "AllowedMethods": ["PUT", "GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    # ETag браузер читает, чтобы подтвердить успешную запись.
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )
    print(f"  CORS разрешён для: {', '.join(origins)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
