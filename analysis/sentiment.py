"""Lexicon-based Korean sentiment scoring (baseline).

This is a transparent, dependency-light baseline: tokenize with kiwipiepy, then
match verb/adjective/noun stems against positive/negative word lists, with a
simple negation flip. It is NOT tuned for heavy slang; swap ``score_text`` for a
model-based scorer later without touching the aggregation API.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from . import db
from .keywords import _kiwi

_DATA = Path(__file__).parent / "data"
# Tags whose stems carry sentiment: adjectives, verbs, nouns, roots.
_SENT_TAGS = {"VA", "VV", "NNG", "NNP", "XR", "VA-I", "VV-I"}


@functools.lru_cache(maxsize=1)
def _lexicon() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    data = json.loads((_DATA / "sentiment_ko.json").read_text(encoding="utf-8"))
    return (frozenset(data["positive"]), frozenset(data["negative"]),
            frozenset(data["negations"]))


def score_text(text: str) -> dict:
    """Return {'pos':int,'neg':int,'score':int,'label':str} for one text."""
    pos_lex, neg_lex, negations = _lexicon()
    if not text:
        return {"pos": 0, "neg": 0, "score": 0, "label": "neutral"}

    tokens = _kiwi().tokenize(text)
    forms = [t.form for t in tokens]
    pos = neg = 0
    for i, tok in enumerate(tokens):
        form = tok.form
        polarity = 0
        if form in pos_lex:
            polarity = 1
        elif form in neg_lex:
            polarity = -1
        if polarity == 0:
            continue
        # Simple negation: flip if a negation token sits within the next 2 tokens
        # (Korean negation often follows: "좋 + 지 + 않"), or immediately before.
        window = forms[i + 1:i + 3] + forms[max(0, i - 1):i]
        if any(n in window for n in negations):
            polarity = -polarity
        if polarity > 0:
            pos += 1
        else:
            neg += 1

    score = pos - neg
    label = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    return {"pos": pos, "neg": neg, "score": score, "label": label}


def _distribution(texts: list[str]) -> dict:
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for t in texts:
        counts[score_text(t)["label"]] += 1
    total = sum(counts.values()) or 1
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "ratio": {k: round(v / total, 3) for k, v in counts.items()},
    }


def sentiment_distribution(db_path: str | Path = db.DEFAULT_DB, *,
                           source: str = "comment", **filters) -> dict:
    """Sentiment label distribution over posts or comments.

    ``source``: 'post' (title+body), 'comment', or 'all'.
    """
    texts: list[str] = []
    if source in ("post", "all"):
        posts = db.load_posts(db_path, exclude_adult=True, **filters)
        if not posts.empty:
            texts += (posts["title"].fillna("") + " " + posts["body_text"].fillna("")).tolist()
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
    result = _distribution(texts)
    result["source"] = source
    return result
