"""Korean keyword analysis using kiwipiepy.

``word_frequency`` returns raw noun counts, used by the word cloud. ``extract_nouns``
is the shared tokenizer (also used by the burst/trend detector); it strips URLs and
inline HTML/CSS that users paste into post bodies before counting.
"""

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
# Users (esp. AI-chat galleries) paste HTML/CSS status-window templates straight
# into the post body as literal text, so ``div``/``px``/``font``/``color`` leak
# in as "nouns". Strip inline markup before tokenizing. This runs on the stored
# text at analysis time, so it cleans existing data too and leaves body_text
# (what the user actually wrote) untouched.
_HTML_TAG = re.compile(r"<[^>]+>")               # <div style="...">, </summary>, ...
_HTML_ENTITY = re.compile(r"&[a-zA-Z#0-9]+;")    # &nbsp; &amp; &#39; ...
_CSS_DECL = re.compile(                          # leftover `property: value;` runs
    r"\b[a-zA-Z-]+\s*:\s*[^;{}<>\n]{1,120};")


def _clean_markup(text: str) -> str:
    """Remove URLs and inline HTML/CSS that users paste into the body as text."""
    text = _HANGUL_URL.sub(" ", text)
    text = _HTML_TAG.sub(" ", text)
    text = _HTML_ENTITY.sub(" ", text)
    text = _CSS_DECL.sub(" ", text)
    return text


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
    text = _clean_markup(text)
    stop = _stopwords()
    out: list[str] = []
    for tok in _kiwi().tokenize(text):
        if tok.tag in _KEEP_TAGS and len(tok.form) >= min_len and tok.form not in stop:
            out.append(tok.form.lower() if tok.tag == "SL" else tok.form)
    return out


def _collect_text(db_path, source: str, filters: dict) -> list[str]:
    """Return a list of documents (each title / body / comment is one doc)."""
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
    """Top-N raw word frequencies. ``source``: title|body|post|comment|all."""
    counter: Counter[str] = Counter()
    for text in _collect_text(db_path, source, filters):
        counter.update(extract_nouns(text, min_len=min_len))
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]
