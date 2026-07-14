"""REST API routes: collection control, browsing, and analysis."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from analysis import db as adb
from analysis import keywords, llm, llm_report, stats, timeseries, trends
from dc_scraper import config as scfg

from .jobs import manager

router = APIRouter(prefix="/api")


def db_path() -> str:
    return os.environ.get("DC_DB_PATH", "dcinside.db")


# --- filters shared by analysis endpoints -----------------------------------
def _filters(gallery_id, date_from, date_to, exclude_adult=False, q=None) -> dict:
    f = {}
    if gallery_id:
        f["gallery_id"] = gallery_id
    if date_from:
        f["date_from"] = date_from
    if date_to:
        f["date_to"] = date_to
    if exclude_adult:
        f["exclude_adult"] = True
    if q:
        f["q"] = q
    return f


# --- collection -------------------------------------------------------------
class CollectRequest(BaseModel):
    gallery_id: str = scfg.DEFAULT_GALLERY_ID
    target_date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    max_pages: int = 100
    with_comments: bool = True
    delay_min: float = 1.0
    delay_max: float = 2.5


@router.post("/collect")
def start_collect(req: CollectRequest) -> dict:
    if req.date_from and req.date_to and req.date_from > req.date_to:
        raise HTTPException(400, "date_from must not be after date_to")
    params = req.model_dump()
    params["db_path"] = db_path()
    job = manager.start(params)
    return {"job_id": job.id, "status": job.status, "params": req.model_dump()}


@router.get("/collect/status")
def collect_status(job_id: str | None = None) -> dict:
    job = manager.get(job_id) if job_id else manager.latest()
    live = None
    if job:
        live = {"id": job.id, "status": job.status, "summary": job.summary,
                "error": job.error, "params": job.params}
    # Also surface the durable run history from the DB.
    runs = []
    try:
        conn = adb.connect(db_path())
        rows = conn.execute(
            "SELECT gallery_id, target_date, started_at, finished_at, posts_found, "
            "posts_saved, comments_saved, status, error FROM scrape_runs "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()
        runs = [dict(r) for r in rows]
        conn.close()
    except Exception:
        pass
    return {"job": live, "runs": runs}


# --- browsing ---------------------------------------------------------------
@router.get("/posts")
def list_posts(
    gallery_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    category: str | None = None,
    sort: str = Query("posted_at", pattern="^(posted_at|recommend|view_count|comment_cnt)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    clauses, params = [], []
    if gallery_id:
        clauses.append("gallery_id = ?")
        params.append(gallery_id)
    if date_from:
        clauses.append("substr(posted_at,1,10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(posted_at,1,10) <= ?")
        params.append(date_to)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if q:
        clauses.append("(title LIKE ? OR body_text LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = adb.connect(db_path())
    total = conn.execute(f"SELECT COUNT(*) FROM posts{where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT post_no,title,writer,posted_at,view_count,recommend,dislike,"
        f"comment_cnt,category,is_adult,url FROM posts{where} "
        f"ORDER BY {sort} {order.upper()} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return {"total": total, "limit": limit, "offset": offset,
            "items": [dict(r) for r in rows]}


@router.get("/posts/{post_no}")
def get_post(post_no: int) -> dict:
    conn = adb.connect(db_path())
    post = conn.execute("SELECT * FROM posts WHERE post_no = ?", (post_no,)).fetchone()
    if not post:
        conn.close()
        raise HTTPException(404, "post not found")
    comments = conn.execute(
        "SELECT writer, writer_ip, content, posted_at, is_reply, parent_no "
        "FROM comments WHERE post_no = ? ORDER BY comment_no", (post_no,)
    ).fetchall()
    conn.close()
    return {"post": dict(post), "comments": [dict(c) for c in comments]}


# --- analysis ---------------------------------------------------------------
@router.get("/stats/overview")
def api_overview(gallery_id: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, q: str | None = None) -> dict:
    return stats.overview(db_path(), **_filters(gallery_id, date_from, date_to, q=q))


@router.get("/stats/top")
def api_top(by: str = "recommend", limit: int = 20, gallery_id: str | None = None,
            date_from: str | None = None, date_to: str | None = None,
            q: str | None = None) -> list[dict]:
    try:
        return stats.top_posts(db_path(), by=by, limit=limit,
                               **_filters(gallery_id, date_from, date_to, q=q))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/stats/categories")
def api_categories(gallery_id: str | None = None, date_from: str | None = None,
                   date_to: str | None = None, q: str | None = None) -> list[dict]:
    return stats.category_distribution(db_path(), **_filters(gallery_id, date_from, date_to, q=q))


@router.get("/analysis/heatmap")
def api_heatmap(gallery_id: str | None = None, date_from: str | None = None,
                date_to: str | None = None, q: str | None = None) -> dict:
    """Weekday × hour activity matrix."""
    return timeseries.heatmap(db_path(), **_filters(gallery_id, date_from, date_to, q=q))


@router.get("/analysis/bursts")
def api_bursts(date: str | None = None, source: str = "post", top_n: int = 20,
               min_count: int = 2, gallery_id: str | None = None,
               date_from: str | None = None, date_to: str | None = None) -> dict:
    """Trending / newly-appearing keywords for a day vs. the preceding days."""
    return trends.daily_bursts(db_path(), date=date, source=source, top_n=top_n,
                               min_count=min_count,
                               **_filters(gallery_id, date_from, date_to))


@router.get("/analysis/keywords")
def api_keywords(source: str = "all", top_n: int = 50,
                 gallery_id: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, q: str | None = None) -> list[dict]:
    """Top-N keyword frequencies (used by the word cloud)."""
    f = _filters(gallery_id, date_from, date_to, q=q)
    return keywords.word_frequency(db_path(), source=source, top_n=top_n, **f)


@router.get("/analysis/llm_status")
def api_llm_status() -> dict:
    """Whether LLM deep-analysis is usable (key + SDK present)."""
    return llm.status()


class LLMReportRequest(BaseModel):
    q: str
    source: str = "post_comment"          # post_comment | post
    refresh: bool = False
    max_posts: int = 60
    gallery_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@router.post("/analysis/llm_report")
def api_llm_report(req: LLMReportRequest) -> dict:
    """LLM qualitative report over posts (+comments) containing a keyword.

    Synchronous: may take a while on large keywords, but results are cached, so
    re-requests are instant. Use ``refresh=true`` to bypass the cache.
    """
    if not req.q or not req.q.strip():
        raise HTTPException(400, "q (키워드) is required")
    if req.source not in ("post_comment", "post"):
        raise HTTPException(400, "source must be post_comment or post")
    f = _filters(req.gallery_id, req.date_from, req.date_to)
    return llm_report.keyword_report(db_path(), keyword=req.q, source=req.source,
                                     refresh=req.refresh, max_posts=req.max_posts, **f)


@router.get("/meta/galleries")
def api_galleries() -> list[dict]:
    """Distinct galleries + date bounds present in the DB (for filter UI)."""
    conn = adb.connect(db_path())
    rows = conn.execute(
        "SELECT gallery_id, COUNT(*) n, MIN(substr(posted_at,1,10)) mn, "
        "MAX(substr(posted_at,1,10)) mx FROM posts GROUP BY gallery_id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
