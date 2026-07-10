"""Parse a post view page: body text/html, e_s_n_o token, vote/view counts."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import config


def _int(text: str | None) -> int:
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_view(html: str) -> dict:
    """Extract detail-page fields from a post view page.

    Returns a dict with: body_text, body_html, e_s_n_o, recommend, dislike,
    view_count. Any field that cannot be located is returned as a safe default
    (empty string / 0 / None) so a partial page never aborts the run.
    """
    # Adult/NSFW posts redirect to /error/adult/ and serve no body unless the
    # session is logged in and age-verified. Detect that up front so callers can
    # flag the post instead of silently storing an empty body.
    if "/error/adult/" in html:
        return {
            "body_text": "",
            "body_html": "",
            "e_s_n_o": None,
            "recommend": 0,
            "dislike": 0,
            "view_count": 0,
            "is_adult": True,
        }

    soup = BeautifulSoup(html, "html.parser")

    body_el = soup.select_one(config.SEL_BODY)
    body_html = body_el.decode_contents() if body_el else ""
    body_text = body_el.get_text("\n", strip=True) if body_el else ""

    esno_el = soup.select_one(config.SEL_ESNO)
    e_s_n_o = esno_el.get("value") if esno_el else None

    rec_el = soup.select_one(config.SEL_VIEW_RECOMMEND)
    dis_el = soup.select_one(config.SEL_VIEW_DISLIKE)
    cnt_el = soup.select_one(config.SEL_VIEW_COUNT)

    return {
        "body_text": body_text,
        "body_html": body_html,
        "e_s_n_o": e_s_n_o,
        "recommend": _int(rec_el.get_text() if rec_el else ""),
        "dislike": _int(dis_el.get_text() if dis_el else ""),
        "view_count": _int(cnt_el.get_text() if cnt_el else ""),
        "is_adult": False,
    }
