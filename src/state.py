"""SQLite-backed per-user state."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

DB_PATH = os.environ.get("STATE_DB_PATH", "/data/state.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_settings (
  telegram_user_id INTEGER PRIMARY KEY,
  default_kb_id    TEXT,
  default_kb_name  TEXT,
  updated_at       TEXT
);
CREATE TABLE IF NOT EXISTS recent_uploads (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_user_id INTEGER,
  kb_id            TEXT,
  kb_name          TEXT,
  filename         TEXT,
  source_type      TEXT,
  created_at       TEXT
);
"""


@dataclass
class UserSettings:
    telegram_user_id: int
    default_kb_id: str | None
    default_kb_name: str | None


@dataclass
class RecentUpload:
    kb_name: str
    filename: str
    source_type: str
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def init_db(path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def get_settings(user_id: int, path: str = DB_PATH) -> UserSettings | None:
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT telegram_user_id, default_kb_id, default_kb_name FROM user_settings WHERE telegram_user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return UserSettings(telegram_user_id=row[0], default_kb_id=row[1], default_kb_name=row[2])


async def set_default_kb(user_id: int, kb_id: str, kb_name: str, path: str = DB_PATH) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """
            INSERT INTO user_settings (telegram_user_id, default_kb_id, default_kb_name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                default_kb_id = excluded.default_kb_id,
                default_kb_name = excluded.default_kb_name,
                updated_at = excluded.updated_at
            """,
            (user_id, kb_id, kb_name, _now_iso()),
        )
        await db.commit()


async def record_upload(
    *,
    user_id: int,
    kb_id: str,
    kb_name: str,
    filename: str,
    source_type: str,
    path: str = DB_PATH,
) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """
            INSERT INTO recent_uploads (telegram_user_id, kb_id, kb_name, filename, source_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, kb_id, kb_name, filename, source_type, _now_iso()),
        )
        await db.commit()


async def recent_uploads(user_id: int, limit: int = 3, path: str = DB_PATH) -> list[RecentUpload]:
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            """
            SELECT kb_name, filename, source_type, created_at
            FROM recent_uploads
            WHERE telegram_user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [RecentUpload(kb_name=r[0], filename=r[1], source_type=r[2], created_at=r[3]) for r in rows]
