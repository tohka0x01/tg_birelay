from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS owners (
                owner_id      INTEGER PRIMARY KEY,
                username      TEXT,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id       INTEGER NOT NULL,
                token          TEXT NOT NULL UNIQUE,
                bot_username   TEXT NOT NULL UNIQUE,
                mode           TEXT NOT NULL DEFAULT 'direct',
                forum_group_id INTEGER,
                created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(owner_id) REFERENCES owners(owner_id)
            );

            CREATE TABLE IF NOT EXISTS direct_routes (
                bot_username   TEXT NOT NULL,
                forward_id     INTEGER NOT NULL,
                user_id        INTEGER NOT NULL,
                created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bot_username, forward_id)
            );

            CREATE TABLE IF NOT EXISTS forum_topics (
                bot_username   TEXT NOT NULL,
                user_id        INTEGER NOT NULL,
                topic_id       INTEGER NOT NULL,
                created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bot_username, user_id)
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                bot_username   TEXT NOT NULL,
                user_id        INTEGER NOT NULL,
                created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bot_username, user_id)
            );

            CREATE TABLE IF NOT EXISTS verified_users (
                bot_username   TEXT NOT NULL,
                user_id        INTEGER NOT NULL,
                verified_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bot_username, user_id)
            );
            """
        )
        self._ensure_column("owners", "manager_start_text", "TEXT")
        self._ensure_column("bots", "client_start_text", "TEXT")
        self._ensure_column("bots", "captcha_enabled", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("bots", "captcha_topics", "TEXT")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        cur = self.conn.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def cursor(self):
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        finally:
            cur.close()

    # ------------ owners & bots ------------
    def upsert_owner(self, owner_id: int, username: str | None) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO owners (owner_id, username)
                VALUES (?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET username=excluded.username
                """,
                (owner_id, username),
            )

    def register_bot(self, owner_id: int, token: str, bot_username: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bots (owner_id, token, bot_username)
                VALUES (?, ?, ?)
                """,
                (owner_id, token, bot_username),
            )

    def remove_bot(self, bot_username: str) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM bots WHERE bot_username=?", (bot_username,))
            cur.execute("DELETE FROM direct_routes WHERE bot_username=?", (bot_username,))
            cur.execute("DELETE FROM forum_topics WHERE bot_username=?", (bot_username,))
            cur.execute("DELETE FROM blacklist WHERE bot_username=?", (bot_username,))
            cur.execute("DELETE FROM verified_users WHERE bot_username=?", (bot_username,))

    def list_bots_for_owner(self, owner_id: int) -> Iterable[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM bots WHERE owner_id=? ORDER BY created_at DESC",
            (owner_id,),
        )
        return cur.fetchall()

    def get_bot(self, bot_username: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM bots WHERE bot_username=?", (bot_username,))
        return cur.fetchone()

    def iter_all_bots(self) -> Iterable[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM bots")
        return cur.fetchall()

    def update_mode(self, bot_username: str, mode: str) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE bots SET mode=? WHERE bot_username=?", (mode, bot_username))

    def set_captcha_enabled(self, bot_username: str, enabled: bool) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE bots SET captcha_enabled=? WHERE bot_username=?",
                (1 if enabled else 0, bot_username),
            )

    def set_captcha_topics(self, bot_username: str, topics: list[str] | None) -> None:
        value = ",".join(topics) if topics else None
        with self.cursor() as cur:
            cur.execute("UPDATE bots SET captcha_topics=? WHERE bot_username=?", (value, bot_username))

    def assign_forum(self, bot_username: str, forum_id: int | None) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE bots SET forum_group_id=? WHERE bot_username=?", (forum_id, bot_username))

    def set_owner_start_text(self, owner_id: int, text: str | None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE owners SET manager_start_text=? WHERE owner_id=?",
                (text, owner_id),
            )

    def get_owner_start_text(self, owner_id: int) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT manager_start_text FROM owners WHERE owner_id=?",
            (owner_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_client_start_text(self, bot_username: str, text: str | None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE bots SET client_start_text=? WHERE bot_username=?",
                (text, bot_username),
            )

    def get_client_start_text(self, bot_username: str) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT client_start_text FROM bots WHERE bot_username=?",
            (bot_username,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    # ------------ direct replies ------------
    def record_forward(self, bot_username: str, forward_id: int, user_id: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO direct_routes (bot_username, forward_id, user_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (bot_username, forward_id, user_id, datetime.utcnow().isoformat()),
            )

    def get_forward_target(self, bot_username: str, forward_id: int) -> Optional[int]:
        cur = self.conn.execute(
            "SELECT user_id FROM direct_routes WHERE bot_username=? AND forward_id=?",
            (bot_username, forward_id),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def pop_forward_target(self, bot_username: str, forward_id: int) -> Optional[int]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM direct_routes WHERE bot_username=? AND forward_id=?",
                (bot_username, forward_id),
            )
            row = cur.fetchone()
            cur.execute(
                "DELETE FROM direct_routes WHERE bot_username=? AND forward_id=?",
                (bot_username, forward_id),
            )
        return row[0] if row else None

    # ------------ forum topics ------------
    def upsert_topic(self, bot_username: str, user_id: int, topic_id: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO forum_topics (bot_username, user_id, topic_id)
                VALUES (?, ?, ?)
                ON CONFLICT(bot_username, user_id) DO UPDATE SET topic_id=excluded.topic_id
                """,
                (bot_username, user_id, topic_id),
            )

    def get_topic(self, bot_username: str, user_id: int) -> Optional[int]:
        cur = self.conn.execute(
            "SELECT topic_id FROM forum_topics WHERE bot_username=? AND user_id=?",
            (bot_username, user_id),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def user_by_topic(self, bot_username: str, topic_id: int) -> Optional[int]:
        cur = self.conn.execute(
            "SELECT user_id FROM forum_topics WHERE bot_username=? AND topic_id=?",
            (bot_username, topic_id),
        )
        row = cur.fetchone()
        return row[0] if row else None

    # ------------ blacklist ------------
    def is_blacklisted(self, bot_username: str, user_id: int) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM blacklist WHERE bot_username=? AND user_id=?",
            (bot_username, user_id),
        )
        return cur.fetchone() is not None

    def add_blacklist(self, bot_username: str, user_id: int) -> bool:
        if self.is_blacklisted(bot_username, user_id):
            return False
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO blacklist (bot_username, user_id) VALUES (?, ?)",
                (bot_username, user_id),
            )
        return True

    def remove_blacklist(self, bot_username: str, user_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM blacklist WHERE bot_username=? AND user_id=?",
                (bot_username, user_id),
            )
            return cur.rowcount > 0

    def list_blacklist(self, bot_username: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT user_id, created_at FROM blacklist WHERE bot_username=? ORDER BY created_at DESC",
            (bot_username,),
        )
        return cur.fetchall()

    def blacklist_count(self, bot_username: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM blacklist WHERE bot_username=?",
            (bot_username,),
        )
        return cur.fetchone()[0]

    # ------------ verified users ------------
    def is_verified(self, bot_username: str, user_id: int) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM verified_users WHERE bot_username=? AND user_id=?",
            (bot_username, user_id),
        )
        return cur.fetchone() is not None

    def verify_user(self, bot_username: str, user_id: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO verified_users (bot_username, user_id)
                VALUES (?, ?)
                ON CONFLICT(bot_username, user_id) DO NOTHING
                """,
                (bot_username, user_id),
            )

    def unverify_user(self, bot_username: str, user_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM verified_users WHERE bot_username=? AND user_id=?",
                (bot_username, user_id),
            )
            return cur.rowcount > 0

    def verified_count(self, bot_username: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM verified_users WHERE bot_username=?",
            (bot_username,),
        )
        return cur.fetchone()[0]
