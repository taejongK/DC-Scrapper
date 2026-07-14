"""Orchestrates the today's-posts collection pipeline."""

from __future__ import annotations

import logging
from datetime import date, datetime

from . import config
from .db import Database
from .fetch import Fetcher
from .parse_comment import fetch_comments
from .parse_list import parse_list
from .parse_view import parse_view

log = logging.getLogger(__name__)


def _list_url(gallery_id: str, page: int) -> str:
    return (f"{config.BASE}/{config.GALLERY_KIND}/board/lists/"
            f"?id={gallery_id}&page={page}")


def _post_date(posted_at: str) -> str:
    """Return the YYYY-MM-DD part of a 'YYYY-MM-DD HH:MM:SS' timestamp."""
    return (posted_at or "")[:10]


def collect(
    *,
    gallery_id: str = config.DEFAULT_GALLERY_ID,
    target_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db_path: str = "dcinside.db",
    fetcher: Fetcher | None = None,
    max_pages: int = config.DEFAULT_MAX_PAGES,
    with_comments: bool = True,
    dry_run: bool = False,
) -> dict:
    """Collect posts authored within a date range (inclusive).

    Pass a single ``target_date`` (default: today) OR a ``date_from``/``date_to``
    range. A single date is treated as ``date_from == date_to``. Dates are
    ``YYYY-MM-DD`` strings compared lexicographically (ISO order == date order).

    Returns a summary dict. When ``dry_run`` is True nothing is written to the
    database and only list metadata is gathered (no body/comment fetches).
    """
    lo, hi = _resolve_range(target_date, date_from, date_to)
    range_label = lo if lo == hi else f"{lo}..{hi}"
    fetcher = fetcher or Fetcher()
    started_at = datetime.now().isoformat(timespec="seconds")

    db = None if dry_run else Database(db_path)
    run_id = db.start_run(gallery_id, range_label, started_at) if db else None

    posts_found = posts_saved = comments_saved = 0
    posts_deleted = comments_deleted = 0
    status = "success"
    error: str | None = None

    try:
        targets, list_complete = _crawl_list(fetcher, gallery_id, lo, hi, max_pages)
        posts_found = len(targets)
        log.info("found %d posts for %s", posts_found, range_label)

        for meta in targets:
            if dry_run:
                continue
            try:
                _process_post(fetcher, db, meta, gallery_id, with_comments)
                posts_saved += 1
                comments_saved += meta.get("_comment_saved", 0)
                comments_deleted += meta.get("_comment_deleted", 0)
                if posts_saved % 10 == 0:
                    db.commit()
            except Exception as exc:  # one bad post must not kill the run
                status = "partial"
                log.warning("post %s failed: %s", meta.get("post_no"), exc)

        # Reflect upstream post deletions: any stored post in this range that the
        # (fully-walked) live list no longer contains has been removed/blinded.
        # Skip when the list walk was cut short by max_pages, or when the run was
        # only partial — in both cases "missing" may just mean "not seen".
        if db and not dry_run and list_complete and status == "success":
            live = {int(m["post_no"]) for m in targets}
            stale = db.post_nos_in_range(gallery_id, lo, hi) - live
            if stale:
                posts_deleted = db.delete_posts(list(stale))
                log.info("removed %d posts deleted upstream: %s",
                         posts_deleted, sorted(stale))
        elif not list_complete:
            log.info("list walk incomplete (max_pages); skipping deletion sweep")

        if db:
            db.commit()
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.exception("run failed")
    finally:
        finished_at = datetime.now().isoformat(timespec="seconds")
        if db and run_id is not None:
            db.finish_run(
                run_id, finished_at=finished_at, posts_found=posts_found,
                posts_saved=posts_saved, comments_saved=comments_saved,
                status=status, error=error,
            )
            db.close()

    return {
        "gallery_id": gallery_id,
        "target_date": range_label,
        "date_from": lo,
        "date_to": hi,
        "posts_found": posts_found,
        "posts_saved": posts_saved,
        "comments_saved": comments_saved,
        "posts_deleted": posts_deleted,
        "comments_deleted": comments_deleted,
        "status": status,
        "error": error,
        "dry_run": dry_run,
    }


def _resolve_range(target_date: str | None, date_from: str | None,
                   date_to: str | None) -> tuple[str, str]:
    """Normalize the various date inputs into an inclusive (lo, hi) pair."""
    if date_from or date_to:
        lo = date_from or date_to
        hi = date_to or date_from
        if lo > hi:
            raise ValueError(f"date_from ({lo}) must not be after date_to ({hi})")
        return lo, hi
    d = target_date or date.today().isoformat()
    return d, d


def _crawl_list(fetcher: Fetcher, gallery_id: str, lo: str, hi: str,
                max_pages: int) -> tuple[list[dict], bool]:
    """Walk list pages collecting posts within [lo, hi]; stop past the range.

    The list is newest-first. Posts newer than ``hi`` (e.g. today, when the
    range is in the past) are skipped without stopping. We stop only once a page
    contains no in-range posts AND at least one article *older than* ``lo`` —
    i.e. we've walked past the oldest edge of the range. Notices are already
    filtered out by parse_list, so they can't hold us back.

    Returns ``(targets, complete)``. ``complete`` is True when the crawl walked
    all the way past the range (or ran out of list pages), so ``targets`` is the
    authoritative set of live posts in the range. It is False when the
    ``max_pages`` safety cap cut the walk short — callers must NOT treat missing
    posts as deleted in that case.
    """
    targets: list[dict] = []
    complete = False
    for page in range(1, max_pages + 1):
        url = _list_url(gallery_id, page)
        html = fetcher.get(url, referer=f"{config.BASE}/{config.GALLERY_KIND}/board/lists?id={gallery_id}").text
        rows = parse_list(html, gallery_id=gallery_id)
        if not rows:
            complete = True
            break

        page_hits = [r for r in rows if lo <= _post_date(r["posted_at"]) <= hi]
        targets.extend(page_hits)

        has_older = any(_post_date(r["posted_at"]) < lo for r in rows)
        if not page_hits and has_older:
            log.info("reached posts older than %s at page %d; stopping", lo, page)
            complete = True
            break
    else:
        log.warning("hit max_pages=%d safety cap while crawling list", max_pages)
    return targets, complete


def _process_post(fetcher: Fetcher, db: Database, meta: dict,
                  gallery_id: str, with_comments: bool) -> None:
    url = meta["url"]
    referer = f"{config.BASE}/{config.GALLERY_KIND}/board/lists?id={gallery_id}"
    view_html = fetcher.get(url, referer=referer).text
    view = parse_view(view_html)

    scraped_at = datetime.now().isoformat(timespec="seconds")
    is_adult = view.get("is_adult", False)
    if is_adult:
        log.info("post %s is adult-gated; storing metadata only", meta["post_no"])
    post = {
        **meta,
        "body_text": view["body_text"],
        "body_html": view["body_html"],
        "is_adult": 1 if is_adult else 0,
        "recommend": view["recommend"] or meta.get("recommend", 0),
        "dislike": view["dislike"],
        "view_count": view["view_count"] or meta.get("view_count", 0),
        "scraped_at": scraped_at,
    }

    comments: list[dict] = []
    comments_fetched = False
    if with_comments and not is_adult and view.get("e_s_n_o"):
        comments = fetch_comments(
            fetcher, gallery_id, meta["post_no"], view["e_s_n_o"], referer=url
        )
        comments_fetched = True
    post["comment_cnt"] = len(comments)
    post.pop("_comment_saved", None)

    db.upsert_post(post)
    for c in comments:
        c["scraped_at"] = scraped_at
        db.upsert_comment(c)

    # Reflect upstream deletions: drop stored comments that vanished from the
    # fresh fetch. Only when we actually fetched — otherwise an empty list would
    # wipe the thread for an adult/skipped post.
    deleted = 0
    if comments_fetched:
        deleted = db.prune_comments(
            meta["post_no"], [c["comment_no"] for c in comments]
        )
    meta["_comment_saved"] = len(comments)
    meta["_comment_deleted"] = deleted
