"""Lexicon-based Korean sentiment scoring (baseline, community-tuned).

Transparent and dependency-light: tokenize with kiwipiepy, match verb/adjective/
noun stems against positive/negative lists, apply an **intensifier** multiplier
(개-, 존나, 핵-, 완전 …) and a negation flip, then fold in **emoticon/repeat**
signals (ㅋㅋ, ㅠㅠ, ^^) from the raw text. Returns discrete counts *and* a
continuous normalized score with a confidence estimate.

This is intended as the offline fallback. The aggregation API
(``sentiment_distribution``) is scorer-agnostic, so ``score_text`` can be
swapped for a model/LLM scorer in Phase 2 without touching callers.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from . import db
from .keywords import _kiwi

_DATA = Path(__file__).parent / "data"
# Tags whose stems carry sentiment: adjectives, verbs, nouns, roots.
_SENT_TAGS = {"VA", "VV", "NNG", "NNP", "XR", "VA-I", "VV-I"}
_INTENSITY = 1.8          # multiplier applied to a word an intensifier modifies
_EMO_POS_W = 0.4          # weight per positive emoticon run (capped)
_EMO_NEG_W = 0.5          # weight per negative emoticon run (capped)


@functools.lru_cache(maxsize=1)
def _lexicon() -> dict:
    data = json.loads((_DATA / "sentiment_ko.json").read_text(encoding="utf-8"))
    return {
        "positive": frozenset(data["positive"]),
        "negative": frozenset(data["negative"]),
        "negations": frozenset(data["negations"]),
        "intensifiers": frozenset(data.get("intensifiers", [])),
        "emo_pos": tuple(data.get("emoticons_positive", [])),
        "emo_neg": tuple(data.get("emoticons_negative", [])),
    }


def _emoticon_signal(text: str, lex: dict) -> float:
    """Weak polarity from emoticons / repeated jamo, capped so it can't dominate."""
    if not text:
        return 0.0
    pos = sum(text.count(e) for e in lex["emo_pos"])
    neg = sum(text.count(e) for e in lex["emo_neg"])
    # long laughter (ㅋㅋㅋ) and crying (ㅠㅠㅠ) runs count once each
    pos += len(re.findall(r"ㅋ{2,}|ㅎ{2,}", text))
    neg += len(re.findall(r"ㅠ{2,}|ㅜ{2,}", text))
    return _EMO_POS_W * min(pos, 2) - _EMO_NEG_W * min(neg, 2)


def score_text(text: str) -> dict:
    """Score one text.

    Returns ``pos``/``neg`` (lexicon hit counts), ``score`` (signed weighted
    total incl. intensifiers + emoticons), ``score_norm`` (score squashed to
    ~[-1, 1]), ``confidence`` (0-1, how much signal was found), and ``label``.
    """
    lex = _lexicon()
    if not text:
        return {"pos": 0, "neg": 0, "score": 0.0, "score_norm": 0.0,
                "confidence": 0.0, "label": "neutral"}

    pos_lex, neg_lex = lex["positive"], lex["negative"]
    negations, intensifiers = lex["negations"], lex["intensifiers"]

    tokens = _kiwi().tokenize(text)
    forms = [t.form for t in tokens]
    pos = neg = 0
    weighted = 0.0
    for i, tok in enumerate(tokens):
        form = tok.form
        polarity = 1 if form in pos_lex else -1 if form in neg_lex else 0
        if polarity == 0:
            continue
        # intensifier: an amplifier within the 2 tokens before this one
        mult = 1.0
        if any(forms[j] in intensifiers for j in range(max(0, i - 2), i)):
            mult = _INTENSITY
        # negation: flip if a negation sits just before or within the next 2 tokens
        window = forms[i + 1:i + 3] + forms[max(0, i - 1):i]
        if any(n in window for n in negations):
            polarity = -polarity
        weighted += polarity * mult
        if polarity > 0:
            pos += 1
        else:
            neg += 1

    emo = _emoticon_signal(text, lex)
    weighted += emo

    hits = pos + neg + (1 if emo else 0)
    # squash to ~[-1,1]; confidence grows with the number of signals found
    score_norm = max(-1.0, min(1.0, weighted / 3.0))
    confidence = round(min(1.0, hits / 5.0), 3)
    label = ("positive" if weighted > 1e-9
             else "negative" if weighted < -1e-9 else "neutral")
    return {"pos": pos, "neg": neg, "score": round(weighted, 3),
            "score_norm": round(score_norm, 3), "confidence": confidence,
            "label": label}


def _distribution(texts: list[str]) -> dict:
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    score_sum = 0.0
    for t in texts:
        res = score_text(t)
        counts[res["label"]] += 1
        score_sum += res["score_norm"]
    total = sum(counts.values())
    denom = total or 1
    return {
        "counts": counts,
        "total": total,
        "ratio": {k: round(v / denom, 3) for k, v in counts.items()},
        "mean_score": round(score_sum / denom, 3),
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
