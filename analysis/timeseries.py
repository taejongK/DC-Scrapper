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


def engagement_by_date(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[dict]:
    """Per-day engagement: post count and total/avg views, recommends, comments."""
    posts = db.load_posts(db_path, **filters)
    if posts.empty:
        return []
    posts = _prep(posts, "posted_at")
    out: list[dict] = []
    for day, grp in posts.groupby(posts["_dt"].dt.date):
        n = len(grp)
        out.append({
            "date": str(day),
            "posts": int(n),
            "views": int(grp["view_count"].fillna(0).sum()),
            "recommend": int(grp["recommend"].fillna(0).sum()),
            "comments": int(grp["comment_cnt"].fillna(0).sum()),
            "avg_views": round(float(grp["view_count"].fillna(0).mean()), 1),
            "avg_comments": round(float(grp["comment_cnt"].fillna(0).mean()), 2),
        })
    return out


def sentiment_by_date(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[dict]:
    """Per-day sentiment trend over posts (title + body), lexicon-based.

    Returns each day's positive/negative/neutral counts and the mean sentiment
    score, so the dashboard can plot how the mood shifts over time.
    """
    from .sentiment import score_text  # local import avoids a module cycle

    posts = db.load_posts(db_path, exclude_adult=True, **filters)
    if posts.empty:
        return []
    posts = _prep(posts, "posted_at")
    out: list[dict] = []
    for day, grp in posts.groupby(posts["_dt"].dt.date):
        counts = {"positive": 0, "negative": 0, "neutral": 0}
        total_score = 0.0
        for _, row in grp.iterrows():
            text = f"{row.get('title') or ''} {row.get('body_text') or ''}"
            res = score_text(text)
            counts[res["label"]] += 1
            total_score += res["score_norm"]  # bounded ~[-1,1] for the trend axis
        n = len(grp) or 1
        out.append({
            "date": str(day),
            "positive": counts["positive"],
            "negative": counts["negative"],
            "neutral": counts["neutral"],
            "mean_score": round(total_score / n, 3),
        })
    return out
