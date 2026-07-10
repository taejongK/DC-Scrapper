"""Korean keyword / word-frequency analysis using kiwipiepy."""

from __future__ import annotations

import functools
import re
from collections import Counter
from pathlib import Path

from . import db

_DATA = Path(__file__).parent / "data"
# Noun-ish POS tags worth counting: general noun, proper noun, root, and
# foreign/alphabet tokens (English brand/model names show up a lot here).
_KEEP_TAGS = {"NNG", "NNP", "SL"}
_HANGUL_URL = re.compile(r"https?://\S+")


@functools.lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi
    return Kiwi()


@functools.lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    path = _DATA / "stopwords_ko.txt"
    words = {w.strip() for w in path.read_text(encoding="utf-8").splitlines() if w.strip()}
    return frozenset(words)


def extract_nouns(text: str, *, min_len: int = 2) -> list[str]:
    """Return content nouns from ``text``, stopword- and length-filtered."""
    if not text:
        return []
    text = _HANGUL_URL.sub(" ", text)
    stop = _stopwords()
    out: list[str] = []
    for tok in _kiwi().tokenize(text):
        if tok.tag in _KEEP_TAGS and len(tok.form) >= min_len and tok.form not in stop:
            out.append(tok.form.lower() if tok.tag == "SL" else tok.form)
    return out


def _collect_text(db_path, source: str, filters: dict) -> list[str]:
    texts: list[str] = []
    if source in ("title", "body", "post", "all"):
        posts = db.load_posts(db_path, exclude_adult=True, **filters)
        if not posts.empty:
            if source in ("title", "post", "all"):
                texts += posts["title"].dropna().tolist()
            if source in ("body", "post", "all"):
                texts += posts["body_text"].dropna().tolist()
    if source in ("comment", "all"):
        comments = db.load_comments(
            db_path,
            gallery_id=filters.get("gallery_id"),
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
            q=filters.get("q"),
        )
        if not comments.empty:
            texts += comments["content"].dropna().tolist()
    return texts


def word_frequency(db_path: str | Path = db.DEFAULT_DB, *, source: str = "all",
                   top_n: int = 50, min_len: int = 2, **filters) -> list[dict]:
    """Top-N word frequencies. ``source``: title|body|post|comment|all."""
    counter: Counter[str] = Counter()
    for text in _collect_text(db_path, source, filters):
        counter.update(extract_nouns(text, min_len=min_len))
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]


def related_words(db_path: str | Path = db.DEFAULT_DB, *, keyword: str,
                  source: str = "all", top_n: int = 30, min_len: int = 2,
                  **filters) -> dict:
    """Words that co-occur with ``keyword`` in the same document.

    Co-occurrence is counted at the document level (a word is counted once per
    document it shares with the keyword), which avoids a single long post
    dominating the ranking. Returns the keyword, how many documents contained
    it, and the top co-occurring words.
    """
    kw = (keyword or "").strip().lower()
    if not kw:
        return {"keyword": keyword, "doc_count": 0, "related": []}

    co: Counter[str] = Counter()
    doc_count = 0
    for text in _collect_text(db_path, source, filters):
        nouns = set(extract_nouns(text, min_len=min_len))
        if kw in nouns:
            doc_count += 1
            nouns.discard(kw)
            co.update(nouns)
    related = [{"word": w, "count": c} for w, c in co.most_common(top_n)]
    return {"keyword": kw, "doc_count": doc_count, "related": related}
