from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Protocol

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


@dataclass
class RunRecord:
    run_id: str
    status: str
    track_path: str
    output_path: str
    youtube_video_id: str
    error_message: str
    created_at: int


class StateStore(Protocol):
    def recent_tracks(self, limit: int) -> list[str]:
        ...

    def recent_clips(self, limit: int) -> list[str]:
        ...

    def mark_track_used(self, track_path: str) -> None:
        ...

    def mark_clips_used(self, clip_urls: list[str]) -> None:
        ...

    def save_run(self, record: RunRecord) -> None:
        ...

    def close(self) -> None:
        ...


class SQLiteStateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS used_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_path TEXT NOT NULL,
                used_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS used_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_url TEXT NOT NULL,
                used_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                track_path TEXT,
                output_path TEXT,
                youtube_video_id TEXT,
                error_message TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        self.conn.commit()

    def recent_tracks(self, limit: int) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT track_path FROM used_tracks ORDER BY used_at DESC LIMIT ?",
            (limit,),
        )
        return [row["track_path"] for row in cur.fetchall()]

    def recent_clips(self, limit: int) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT clip_url FROM used_clips ORDER BY used_at DESC LIMIT ?",
            (limit,),
        )
        return [row["clip_url"] for row in cur.fetchall()]

    def mark_track_used(self, track_path: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO used_tracks(track_path, used_at) VALUES (?, ?)",
            (track_path, int(time.time())),
        )
        self.conn.commit()

    def mark_clips_used(self, clip_urls: list[str]) -> None:
        cur = self.conn.cursor()
        now = int(time.time())
        cur.executemany(
            "INSERT INTO used_clips(clip_url, used_at) VALUES (?, ?)",
            [(url, now) for url in clip_urls],
        )
        self.conn.commit()

    def save_run(self, record: RunRecord) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO runs(run_id, status, track_path, output_path, youtube_video_id, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.status,
                record.track_path,
                record.output_path,
                record.youtube_video_id,
                record.error_message,
                record.created_at,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class PostgresStateStore:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgresStateStore")
        self.conn = psycopg.connect(database_url)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS used_tracks (
                    id SERIAL PRIMARY KEY,
                    track_path TEXT NOT NULL,
                    used_at BIGINT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS used_clips (
                    id SERIAL PRIMARY KEY,
                    clip_url TEXT NOT NULL,
                    used_at BIGINT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id SERIAL PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    track_path TEXT,
                    output_path TEXT,
                    youtube_video_id TEXT,
                    error_message TEXT,
                    created_at BIGINT NOT NULL
                )
                """
            )
        self.conn.commit()

    def recent_tracks(self, limit: int) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT track_path FROM used_tracks ORDER BY used_at DESC LIMIT %s",
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]

    def recent_clips(self, limit: int) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT clip_url FROM used_clips ORDER BY used_at DESC LIMIT %s",
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]

    def mark_track_used(self, track_path: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO used_tracks(track_path, used_at) VALUES (%s, %s)",
                (track_path, int(time.time())),
            )
        self.conn.commit()

    def mark_clips_used(self, clip_urls: list[str]) -> None:
        if not clip_urls:
            return
        now = int(time.time())
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO used_clips(clip_url, used_at) VALUES (%s, %s)",
                [(url, now) for url in clip_urls],
            )
        self.conn.commit()

    def save_run(self, record: RunRecord) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs(run_id, status, track_path, output_path, youtube_video_id, error_message, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.run_id,
                    record.status,
                    record.track_path,
                    record.output_path,
                    record.youtube_video_id,
                    record.error_message,
                    record.created_at,
                ),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def create_state_store(db_path: Path, database_url: str = "") -> StateStore:
    if database_url:
        return PostgresStateStore(database_url)
    return SQLiteStateStore(db_path)
