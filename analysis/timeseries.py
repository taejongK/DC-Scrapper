"""Time-based activity trends: by date, hour-of-day, and weekday."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import db

_WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _prep(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df = df.copy()
    df["_dt"] = pd.to_datetime(df[col], errors="coerce", format="mixed")
    return df.dropna(subset=["_dt"])


def by_date(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[dict]:
    posts = db.load_posts(db_path, **filters)
    if posts.empty:
        return []
    posts = _prep(posts, "posted_at")
    g = posts.groupby(posts["_dt"].dt.date).size()
    return [{"date": str(d), "count": int(n)} for d, n in g.items()]


def by_hour(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[dict]:
    posts = db.load_posts(db_path, **filters)
    if posts.empty:
        return [{"hour": h, "count": 0} for h in range(24)]
    posts = _prep(posts, "posted_at")
    counts = posts["_dt"].dt.hour.value_counts()
    return [{"hour": h, "count": int(counts.get(h, 0))} for h in range(24)]


def by_weekday(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[dict]:
    posts = db.load_posts(db_path, **filters)
    result = [{"weekday": w, "count": 0} for w in _WEEKDAYS_KO]
    if posts.empty:
        return result
    posts = _prep(posts, "posted_at")
    counts = posts["_dt"].dt.weekday.value_counts()
    for i, w in enumerate(_WEEKDAYS_KO):
        result[i]["count"] = int(counts.get(i, 0))
    return result
