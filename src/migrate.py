"""Версионированные миграции схемы.

Существующие стораджи создают таблицы через CREATE TABLE IF NOT EXISTS при
старте. Для мультиарендной части этого мало: там лежат чужие токены и чужой
контент, и нужно знать, какая версия схемы реально применена.

Запуск:
    python -m src.migrate            # применить непринятые
    python -m src.migrate --status   # показать состояние, ничего не менять
    python -m src.migrate --tables   # показать фактические таблицы схемы
"""

from __future__ import annotations

from pathlib import Path
import sys

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _connect(database_url: str):
    if psycopg is None:
        raise RuntimeError("psycopg is required to run migrations")
    if not database_url.strip():
        raise RuntimeError("DATABASE_URL is empty; migrations need Postgres")
    return psycopg.connect(database_url)


def _ensure_bookkeeping(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def _applied(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def discover() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def apply_pending(database_url: str) -> list[str]:
    """Применяет непринятые миграции. Возвращает список применённых версий."""
    applied_now: list[str] = []
    with _connect(database_url) as conn:
        _ensure_bookkeeping(conn)
        done = _applied(conn)
        for path in discover():
            version = path.stem
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            # Каждая миграция — одна транзакция: либо целиком, либо никак.
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
            applied_now.append(version)
    return applied_now


def status(database_url: str) -> tuple[list[str], list[str]]:
    """Возвращает (применённые, ожидающие)."""
    with _connect(database_url) as conn:
        _ensure_bookkeeping(conn)
        done = _applied(conn)
    found = [p.stem for p in discover()]
    return sorted(done), [v for v in found if v not in done]


def tables(database_url: str) -> list[tuple[str, int]]:
    """Фактические таблицы схемы public и число колонок в каждой."""
    with _connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.table_name,
                   (SELECT count(*) FROM information_schema.columns c
                     WHERE c.table_schema = 'public'
                       AND c.table_name = t.table_name)
              FROM information_schema.tables t
             WHERE t.table_schema = 'public'
               AND t.table_type = 'BASE TABLE'
             ORDER BY t.table_name
            """
        )
        return [(row[0], int(row[1])) for row in cur.fetchall()]


def main() -> None:
    import os

    database_url = os.getenv("DATABASE_URL", "")

    if "--status" in sys.argv:
        done, pending = status(database_url)
        print(f"применено: {', '.join(done) or '-'}")
        print(f"ожидает  : {', '.join(pending) or '-'}")
        return

    if "--tables" in sys.argv:
        rows = tables(database_url)
        print(f"{len(rows)} таблиц:")
        for name, cols in rows:
            print(f"  {name:22} {cols} колонок")
        return

    applied_now = apply_pending(database_url)
    if applied_now:
        print(f"применено: {', '.join(applied_now)}")
    else:
        print("новых миграций нет")


if __name__ == "__main__":
    main()
