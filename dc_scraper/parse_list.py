"""Parse a gallery list page into post metadata dicts."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import config


def _int(text: str | None) -> int:
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_list(html: str, *, gallery_id: str = config.DEFAULT_GALLERY_ID) -> list[dict]:
    """Return a list of post-meta dicts from a list page.

    Notice/non-article rows (말머리 in NOTICE_SUBJECTS) are excluded.
    `posted_at` is taken from the `.gall_date` `title` attribute, which always
    holds the full ``YYYY-MM-DD HH:MM:SS`` timestamp (the visible text collapses
    to just a time for same-day posts).
    """
    soup = BeautifulSoup(html, "html.parser")
    posts: list[dict] = []

    for tr in soup.select(config.ROW_SELECTOR):
        subj_el = tr.select_one(config.SEL_SUBJECT)
        subject = subj_el.get_text(strip=True) if subj_el else ""
        if subject in config.NOTICE_SUBJECTS:
            continue

        num_el = tr.select_one(config.SEL_NUM)
        num_txt = num_el.get_text(strip=True) if num_el else ""
        if not num_txt.isdigit():
            # Defensive: AD / promo rows sometimes lack a numeric id.
            continue
        post_no = int(num_txt)

        date_el = tr.select_one(config.SEL_DATE)
        posted_at = (date_el.get("title") or date_el.get_text(strip=True)) if date_el else ""

        title_el = tr.select_one(config.SEL_TITLE)
        title = title_el.get_text(" ", strip=True) if title_el else ""
        href = title_el.get("href") if title_el else None
        url = urljoin(config.BASE, href) if href else (
            f"{config.BASE}/{config.GALLERY_KIND}/board/view/?id={gallery_id}&no={post_no}"
        )

        writer_el = tr.select_one(config.SEL_WRITER)
        writer = writer_el.get("data-nick") if writer_el else None
        if not writer and writer_el:
            writer = writer_el.get_text(strip=True)
        writer_ip = writer_el.get("data-ip") if writer_el else None
        writer_uid = writer_el.get("data-uid") if writer_el else None

        posts.append(
            {
                "post_no": post_no,
                "gallery_id": gallery_id,
                "category": subject or None,
                "title": title,
                "posted_at": posted_at,
                "writer": writer or None,
                "writer_ip": writer_ip or None,
                "writer_uid": writer_uid or None,
                "view_count": _int(tr.select_one(config.SEL_COUNT).get_text() if tr.select_one(config.SEL_COUNT) else ""),
                "recommend": _int(tr.select_one(config.SEL_RECOMMEND).get_text() if tr.select_one(config.SEL_RECOMMEND) else ""),
                "url": url,
            }
        )

    return posts
