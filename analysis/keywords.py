"""Korean keyword analysis using kiwipiepy.

Three levels of keyword extraction, cheapest first:

* ``word_frequency`` — raw noun counts (kept for word clouds / back-compat).
* ``salient_words`` — TF-IDF weighted terms so ubiquitous-but-empty words stop
  dominating the ranking; this is the "distinctive keyword" view.
* ``related_words`` — words that co-occur with a keyword, ranked by PMI so that
  merely-common words don't attach to every keyword.

Terms include noun **bigrams** (adjacent content nouns) so multi-word concepts
like "○○ 업데이트" surface as a single term.
"""

from __future__ import annotations

import functools
import math
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


def extract_terms(text: str, *, min_len: int = 2, bigrams: bool = True) -> list[str]:
    """Nouns plus adjacent-noun bigrams.

    Bigrams are formed only from nouns that were *adjacent in the token stream*,
    so "에덴 캐릭터" becomes the term "에덴 캐릭터" but words split by a verb do
    not glue together. Unigrams are always kept alongside their bigrams.
    """
    if not text:
        return []
    text = _clean_markup(text)
    stop = _stopwords()
    toks = _kiwi().tokenize(text)

    terms: list[str] = []
    prev: str | None = None
    prev_adjacent_end = -1
    for tok in toks:
        keep = tok.tag in _KEEP_TAGS and len(tok.form) >= min_len and tok.form not in stop
        if not keep:
            prev = None
            continue
        form = tok.form.lower() if tok.tag == "SL" else tok.form
        terms.append(form)
        if bigrams and prev is not None and tok.start == prev_adjacent_end:
            terms.append(f"{prev} {form}")
        prev = form
        # kiwipiepy tokens carry .start/.len; adjacency = next token starts where
        # this one ends (ignoring a single space is handled by <= start+1).
        prev_adjacent_end = tok.start + tok.len + 1
    return terms


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


def salient_words(db_path: str | Path = db.DEFAULT_DB, *, source: str = "all",
                  top_n: int = 50, min_len: int = 2, bigrams: bool = True,
                  **filters) -> list[dict]:
    """Distinctive keywords via TF-IDF over the selected documents.

    ``score = (1 + log tf) * log((1 + N) / (1 + df))``. Terms that appear in
    almost every document (low information) are pushed down even if frequent,
    while terms concentrated in few documents rise. Returns ``count`` (raw term
    frequency) and ``score`` (TF-IDF), sorted by score.
    """
    docs = _collect_text(db_path, source, filters)
    tf: Counter[str] = Counter()
    df: Counter[str] = Counter()
    n_docs = 0
    for text in docs:
        terms = extract_terms(text, min_len=min_len, bigrams=bigrams)
        if not terms:
            continue
        n_docs += 1
        tf.update(terms)
        df.update(set(terms))
    if n_docs == 0:
        return []
    scored: list[dict] = []
    for term, freq in tf.items():
        idf = math.log((1 + n_docs) / (1 + df[term])) + 1.0
        score = (1.0 + math.log(freq)) * idf
        scored.append({"word": term, "count": freq, "score": round(score, 4)})
    scored.sort(key=lambda d: (d["score"], d["count"]), reverse=True)
    return scored[:top_n]


def related_words(db_path: str | Path = db.DEFAULT_DB, *, keyword: str,
                  source: str = "all", top_n: int = 30, min_len: int = 2,
                  min_cooccur: int = 1, **filters) -> dict:
    """Words that co-occur with ``keyword``, ranked by PMI.

    Co-occurrence is document-level (a word counts once per document it shares
    with the keyword). Ranking by pointwise mutual information
    ``pmi = log( p(w, kw) / (p(w) p(kw)) )`` rewards words that appear *unusually
    often* alongside the keyword rather than words that are simply common. Ties
    break on co-occurrence count. Returns the keyword, its document frequency,
    and the top related words with ``count`` (co-occurrence) and ``score`` (PMI).
    """
    kw = (keyword or "").strip().lower()
    if not kw:
        return {"keyword": keyword, "doc_count": 0, "related": []}

    doc_terms: list[set[str]] = []
    df: Counter[str] = Counter()
    for text in _collect_text(db_path, source, filters):
        terms = set(extract_nouns(text, min_len=min_len))
        if not terms:
            continue
        doc_terms.append(terms)
        df.update(terms)

    n_docs = len(doc_terms)
    kw_df = df.get(kw, 0)
    if kw_df == 0 or n_docs == 0:
        return {"keyword": kw, "doc_count": 0, "related": []}

    co: Counter[str] = Counter()
    for terms in doc_terms:
        if kw in terms:
            for w in terms:
                if w != kw:
                    co[w] += 1

    scored: list[dict] = []
    for w, c in co.items():
        if c < min_cooccur:
            continue
        # pmi = log( (c/N) / ((kw_df/N) * (df_w/N)) ) = log( c * N / (kw_df * df_w) )
        pmi = math.log((c * n_docs) / (kw_df * df[w]))
        scored.append({"word": w, "count": c, "score": round(pmi, 4)})
    scored.sort(key=lambda d: (d["score"], d["count"]), reverse=True)
    return {"keyword": kw, "doc_count": kw_df, "related": scored[:top_n]}
