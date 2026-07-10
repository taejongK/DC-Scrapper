"""Fetch and parse comments via the DCInside comment AJAX endpoint.

The endpoint returns JSON:
    {"total_cnt": N, "comment_cnt": M, "comments": [ {...}, ... ], ...}
Each comment: no, parent, user_id, name, ip, reg_date ("MM.DD HH:MM:SS"),
depth, memo (HTML), del_yn, is_delete, rcnt (# of replies), ...
Top-level comments have depth 0; replies have depth > 0.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import config
from .fetch import Fetcher


def _build_payload(gallery_id: str, post_no: int, e_s_n_o: str, page: int) -> dict:
    return {
        "id": gallery_id,
        "no": str(post_no),
        "cmt_id": gallery_id,
        "cmt_no": str(post_no),
        "e_s_n_o": e_s_n_o,
        "comment_page": str(page),
        "_GALLTYPE_": config.GALLTYPE,
    }


def _clean(memo_html: str | None) -> str:
    if not memo_html:
        return ""
    return BeautifulSoup(memo_html, "html.parser").get_text("\n", strip=True)


def _to_int(val) -> int | None:
    if val is None:
        return None
    s = re.sub(r"[^\d]", "", str(val))
    return int(s) if s else None


def parse_comment_json(data: dict, post_no: int) -> list[dict]:
    """Convert one page of comment JSON into normalized comment dicts.

    Ad/placeholder rows (no numeric `no`, or `vr_type`/`voice`-only entries) are
    skipped. Deleted comments are kept but flagged via empty content.
    """
    out: list[dict] = []
    for c in data.get("comments") or []:
        cno = _to_int(c.get("no"))
        # no==0 is DCInside's "댓글돌이" ad/news-roller row, not a real comment.
        if not cno:
            continue
        depth = _to_int(c.get("depth")) or 0
        parent = _to_int(c.get("parent"))
        # For top-level comments DCInside sets parent = post_no; normalize to None.
        parent_no = None if (parent == post_no or depth == 0) else parent
        deleted = c.get("del_yn") == "Y" or str(c.get("is_delete")) == "1"
        out.append(
            {
                "post_no": post_no,
                "comment_no": cno,
                "parent_no": parent_no,
                "writer": c.get("name") or None,
                "writer_ip": c.get("ip") or None,
                "content": "" if deleted else _clean(c.get("memo")),
                "posted_at": c.get("reg_date") or None,
                "is_reply": 1 if depth and depth > 0 else 0,
            }
        )
    return out


def fetch_comments(fetcher: Fetcher, gallery_id: str, post_no: int,
                   e_s_n_o: str, *, referer: str,
                   max_pages: int = 50) -> list[dict]:
    """Fetch all comment pages for a post and return normalized comment dicts."""
    all_comments: list[dict] = []
    seen: set[int] = set()
    page = 1
    while page <= max_pages:
        payload = _build_payload(gallery_id, post_no, e_s_n_o, page)
        resp = fetcher.post(config.COMMENT_ENDPOINT, payload, referer=referer)
        try:
            data = resp.json()
        except ValueError:
            break
        parsed = parse_comment_json(data, post_no)
        fresh = [c for c in parsed if c["comment_no"] not in seen]
        if not fresh:
            break
        for c in fresh:
            seen.add(c["comment_no"])
        all_comments.extend(fresh)

        # Stop when we've collected the reported total, or no more pages.
        total = _to_int(data.get("total_cnt")) or 0
        if total and len(seen) >= total:
            break
        page += 1

    return all_comments
