"""Issue / burst detection over time.

Answers *"what blew up today?"* by comparing each term's share of a target
day's posts against its share across the preceding baseline days. Terms that
spike (or appear for the first time) rank highest.

Scope note: trends run over **posts** (title + body). Comment timestamps in the
source lack a year, so they are excluded here to keep day-bucketing reliable.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import db
from .keywords import extract_nouns

_EPS = 1e-9


def _daily_terms(db_path, source: str, filters: dict) -> dict[str, Counter]:
    """Map ``YYYY-MM-DD`` -> Counter of terms from that day's posts."""
    posts = db.load_posts(db_path, exclude_adult=True, **filters)
    per_day: dict[str, Counter] = {}
    if posts.empty:
        return per_day
    for _, row in posts.iterrows():
        day = str(row["posted_at"])[:10]
        if not day.strip():
            continue
        texts = []
        if source in ("title", "post"):
            texts.append(row.get("title") or "")
        if source in ("body", "post"):
            texts.append(row.get("body_text") or "")
        bag = per_day.setdefault(day, Counter())
        for text in texts:
            bag.update(extract_nouns(text))
    return per_day


def available_dates(db_path: str | Path = db.DEFAULT_DB, **filters) -> list[str]:
    """Sorted list of dates (ascending) that have posts."""
    return sorted(_daily_terms(db_path, "post", filters))


def daily_bursts(db_path: str | Path = db.DEFAULT_DB, *, date: str | None = None,
                 source: str = "post", top_n: int = 20, min_count: int = 2,
                 **filters) -> dict:
    """Terms spiking on ``date`` versus the preceding days.

    ``date`` defaults to the most recent day with posts. For each term appearing
    at least ``min_count`` times on the target day, a burst ratio compares its
    share of that day's terms to its share across all earlier days (Laplace-
    smoothed). ``is_new`` marks terms unseen in the baseline. Returns the target
    date, the baseline range, and terms sorted by burst ratio.
    """
    per_day = _daily_terms(db_path, source, filters)
    if not per_day:
        return {"date": None, "baseline_days": 0, "bursts": [], "new_keywords": []}

    days = sorted(per_day)
    target = date or days[-1]
    if target not in per_day:
        return {"date": target, "baseline_days": 0, "bursts": [], "new_keywords": []}

    baseline_days = [d for d in days if d < target]
    today = per_day[target]
    today_total = sum(today.values()) or 1

    base = Counter()
    for d in baseline_days:
        base.update(per_day[d])
    base_total = sum(base.values())

    bursts: list[dict] = []
    new_keywords: list[dict] = []
    # smoothing over vocabulary size so a single stray word isn't "infinitely" hot
    vocab = len(set(today) | set(base)) or 1
    for term, c in today.items():
        if c < min_count:
            continue
        today_share = c / today_total
        base_share = (base.get(term, 0) + 1) / (base_total + vocab)
        ratio = today_share / (base_share + _EPS)
        item = {"word": term, "count": c, "burst": round(ratio, 3),
                "is_new": term not in base}
        bursts.append(item)
        if item["is_new"]:
            new_keywords.append({"word": term, "count": c})

    bursts.sort(key=lambda d: (d["burst"], d["count"]), reverse=True)
    new_keywords.sort(key=lambda d: d["count"], reverse=True)
    return {
        "date": target,
        "baseline_from": baseline_days[0] if baseline_days else None,
        "baseline_to": baseline_days[-1] if baseline_days else None,
        "baseline_days": len(baseline_days),
        "bursts": bursts[:top_n],
        "new_keywords": new_keywords[:top_n],
    }
