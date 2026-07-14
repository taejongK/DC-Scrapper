"""Weekday × hour activity heatmap."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import db

_WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _prep(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df = df.copy()
    df["_dt"] = pd.to_datetime(df[col], errors="coerce", format="mixed")
    return df.dropna(subset=["_dt"])


def heatmap(db_path: str | Path = db.DEFAULT_DB, **filters) -> dict:
    """Weekday × hour activity matrix (post counts).

    Returns ``{"weekdays": [...7...], "matrix": [[...24...] × 7]}`` where
    ``matrix[w][h]`` is the number of posts written on weekday ``w`` at hour
    ``h``. Handy for spotting the community's active windows at a glance.
    """
    matrix = [[0] * 24 for _ in range(7)]
    posts = db.load_posts(db_path, **filters)
    if not posts.empty:
        posts = _prep(posts, "posted_at")
        g = posts.groupby([posts["_dt"].dt.weekday, posts["_dt"].dt.hour]).size()
        for (wd, hr), n in g.items():
            matrix[int(wd)][int(hr)] = int(n)
    return {"weekdays": _WEEKDAYS_KO, "matrix": matrix}
