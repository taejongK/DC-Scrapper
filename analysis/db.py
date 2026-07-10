"""Read-only data access + pandas loaders for the analysis layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB = "dcinside.db"


def connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open a read-only-ish connection (we never write from the analysis layer)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _where(gallery_id: str | None, date_from: str | None, date_to: str | None,
           exclude_adult: bool, q: str | None = None) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if gallery_id:
        clauses.append("gallery_id = ?")
        params.append(gallery_id)
    if date_from:
        clauses.append("substr(posted_at,1,10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(posted_at,1,10) <= ?")
        params.append(date_to)
    if exclude_adult:
        clauses.append("COALESCE(is_adult,0) = 0")
    if q:
        clauses.append("(title LIKE ? OR body_text LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def load_posts(
    db_path: str | Path = DEFAULT_DB,
    *,
    gallery_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    exclude_adult: bool = False,
    q: str | None = None,
) -> pd.DataFrame:
    """Load posts as a DataFrame with a parsed ``posted_dt`` datetime column.

    ``q`` restricts to posts whose title or body contains the substring.
    """
    where, params = _where(gallery_id, date_from, date_to, exclude_adult, q)
    with connect(db_path) as conn:
        df = pd.read_sql_query(f"SELECT * FROM posts{where}", conn, params=params)
    if not df.empty:
        df["posted_dt"] = pd.to_datetime(df["posted_at"], errors="coerce")
    return df


def load_comments(
    db_path: str | Path = DEFAULT_DB,
    *,
    gallery_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
) -> pd.DataFrame:
    """Load comments joined to their post's gallery/date for filtering.

    ``q`` restricts to comments belonging to posts whose title/body contains the
    substring, keeping the keyword scope consistent with post-level analysis.
    """
    clauses: list[str] = []
    params: list = []
    if gallery_id:
        clauses.append("p.gallery_id = ?")
        params.append(gallery_id)
    if date_from:
        clauses.append("substr(p.posted_at,1,10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(p.posted_at,1,10) <= ?")
        params.append(date_to)
    if q:
        clauses.append("(p.title LIKE ? OR p.body_text LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT c.* FROM comments c JOIN posts p ON p.post_no = c.post_no" + where
    )
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)
