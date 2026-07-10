"""Overview statistics and popular-post rankings."""

from __future__ import annotations

from pathlib import Path

from . import db

SORT_COLUMNS = {"recommend", "view_count", "comment_cnt", "dislike"}


def overview(db_path: str | Path = db.DEFAULT_DB, **filters) -> dict:
    posts = db.load_posts(db_path, **filters)
    comments = db.load_comments(
        db_path,
        gallery_id=filters.get("gallery_id"),
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
        q=filters.get("q"),
    )
    if posts.empty:
        return {
            "posts": 0, "comments": 0, "unique_writers": 0,
            "date_from": None, "date_to": None, "adult_posts": 0,
            "avg_comments": 0.0, "avg_views": 0.0,
        }
    dates = posts["posted_at"].str.slice(0, 10)
    return {
        "posts": int(len(posts)),
        "comments": int(len(comments)),
        "unique_writers": int(posts["writer"].nunique()),
        "date_from": dates.min(),
        "date_to": dates.max(),
        "adult_posts": int(posts.get("is_adult", 0).fillna(0).astype(int).sum())
                       if "is_adult" in posts else 0,
        "avg_comments": round(float(posts["comment_cnt"].mean()), 2),
        "avg_views": round(float(posts["view_count"].mean()), 2),
    }


def top_posts(db_path: str | Path = db.DEFAULT_DB, *, by: str = "recommend",
              limit: int = 20, **filters) -> list[dict]:
    if by not in SORT_COLUMNS:
        raise ValueError(f"invalid sort column: {by} (allowed: {sorted(SORT_COLUMNS)})")
    posts = db.load_posts(db_path, **filters)
    if posts.empty:
        return []
    cols = ["post_no", "title", "writer", "posted_at", "view_count",
            "recommend", "dislike", "comment_cnt", "category", "url"]
    top = posts.sort_values(by, ascending=False).head(limit)[cols]
    return top.to_dict(orient="records")


def category_distribution(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[dict]:
    posts = db.load_posts(db_path, **filters)
    if posts.empty:
        return []
    counts = posts["category"].fillna("(없음)").value_counts()
    return [{"category": k, "count": int(v)} for k, v in counts.items()]
