"""SQLite persistence layer with idempotent upserts.

Schema is intentionally close to PostgreSQL-compatible so a future backend
switch is mechanical. Natural keys (post_no, (post_no, comment_no)) make
re-runs idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    post_no      INTEGER PRIMARY KEY,
    gallery_id   TEXT NOT NULL,
    title        TEXT NOT NULL,
    writer       TEXT,
    writer_ip    TEXT,
    writer_uid   TEXT,
    posted_at    TEXT NOT NULL,
    view_count   INTEGER DEFAULT 0,
    recommend    INTEGER DEFAULT 0,
    dislike      INTEGER DEFAULT 0,
    comment_cnt  INTEGER DEFAULT 0,
    category     TEXT,
    body_text    TEXT,
    body_html    TEXT,
    is_adult     INTEGER DEFAULT 0,
    url          TEXT NOT NULL,
    scraped_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_no      INTEGER NOT NULL,
    comment_no   INTEGER,
    parent_no    INTEGER,
    writer       TEXT,
    writer_ip    TEXT,
    content      TEXT,
    posted_at    TEXT,
    is_reply     INTEGER DEFAULT 0,
    scraped_at   TEXT NOT NULL,
    UNIQUE(post_no, comment_no)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id     TEXT NOT NULL,
    target_date    TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    posts_found    INTEGER DEFAULT 0,
    posts_saved    INTEGER DEFAULT 0,
    comments_saved INTEGER DEFAULT 0,
    status         TEXT,
    error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(posted_at);
CREATE INDEX IF NOT EXISTS idx_comments_post_no ON comments(post_no);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Additive migrations for DBs created by an earlier schema version."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(posts)")}
        if "is_adult" not in cols:
            self.conn.execute("ALTER TABLE posts ADD COLUMN is_adult INTEGER DEFAULT 0")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- posts ---------------------------------------------------------------
    def upsert_post(self, post: dict) -> None:
        cols = [
            "post_no", "gallery_id", "title", "writer", "writer_ip", "writer_uid",
            "posted_at", "view_count", "recommend", "dislike", "comment_cnt",
            "category", "body_text", "body_html", "is_adult", "url", "scraped_at",
        ]
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "post_no")
        row = {c: post.get(c) for c in cols}
        self.conn.execute(
            f"INSERT INTO posts ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(post_no) DO UPDATE SET {updates}",
            row,
        )

    def upsert_comment(self, comment: dict) -> None:
        cols = [
            "post_no", "comment_no", "parent_no", "writer", "writer_ip",
            "content", "posted_at", "is_reply", "scraped_at",
        ]
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols
                            if c not in ("post_no", "comment_no"))
        row = {c: comment.get(c) for c in cols}
        self.conn.execute(
            f"INSERT INTO comments ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(post_no, comment_no) DO UPDATE SET {updates}",
            row,
        )

    # -- run tracking --------------------------------------------------------
    def start_run(self, gallery_id: str, target_date: str, started_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO scrape_runs (gallery_id, target_date, started_at, status) "
            "VALUES (?, ?, ?, 'running')",
            (gallery_id, target_date, started_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, finished_at: str, posts_found: int,
                   posts_saved: int, comments_saved: int, status: str,
                   error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE scrape_runs SET finished_at=?, posts_found=?, posts_saved=?, "
            "comments_saved=?, status=?, error=? WHERE id=?",
            (finished_at, posts_found, posts_saved, comments_saved, status, error, run_id),
        )
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def count_posts_for_date(self, date_prefix: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE posted_at LIKE ?", (f"{date_prefix}%",)
        )
        return int(cur.fetchone()[0])
