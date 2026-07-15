"""LLM-based qualitative report for one or more keywords.

Gathers every (non-adult) post whose title/body contains **any** of the given
keywords — with its comments — and asks the LLM what people are actually saying:
the gist, the positive/negative evaluations, the points of contention, and
representative quotes. Word-frequency views tell you *which* words show up; this
tells you *what is being said*.

Each finding (theme / positive / negative / issue) carries the post numbers it
was drawn from, so the UI can link back to the source posts as evidence.

Large keyword sets are handled map-reduce style: documents are batched, each
batch summarized, then the partials synthesized into one report. Results are
cached in the DB so re-opening a report costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from . import db, llm

# document-shaping budgets (chars) — keep batches comfortably within context
_BODY_CHARS = 800
_CMT_CHARS = 180
_MAX_CMTS = 15
_BATCH_CHARS = 14000
_DEFAULT_MAX_POSTS = 60

_SCHEMA_HINT = (
    '{"overview": "2~4문장 전체 요약", "mood": "전반적 분위기와 긍/부정 경향", '
    '"themes": [{"title": "소주제", "detail": "무슨 얘기가 오갔는지", "post_nos": [글번호,...]}], '
    '"positives": [{"text": "긍정 평가", "post_nos": [글번호,...]}], '
    '"negatives": [{"text": "부정 평가", "post_nos": [글번호,...]}], '
    '"issues": [{"text": "쟁점/논쟁", "post_nos": [글번호,...]}], '
    '"quotes": [{"quote": "대표 인용", "post_no": 글번호}]}'
)
_EVIDENCE_RULE = (
    " 모든 themes/positives/negatives/issues 항목에는 그 판단의 근거가 된 글 번호를 "
    "post_nos 배열로 반드시 포함하라. 글 번호는 입력의 '[글 #숫자]' 표기에서 가져온다. "
    "근거 없는 항목은 만들지 마라."
)

_SINGLE_SYS = (
    "너는 한국어 커뮤니티(디시인사이드) 여론 분석가다. 주어진 글·댓글에서 특정 키워드에 "
    "대해 사람들이 무슨 이야기를 하고 어떻게 평가하는지 분석한다. 슬랭/은어/반어를 감안하라. "
    "JSON으로만 반환한다: " + _SCHEMA_HINT + _EVIDENCE_RULE
)
_MAP_SYS = (
    "너는 한국어 커뮤니티 여론 분석가다. 주어진 글·댓글 묶음에서 특정 키워드에 대해 사람들이 "
    "무슨 이야기를 하는지 분석한다. 슬랭/은어/반어를 감안하라. JSON으로만 반환한다: "
    + _SCHEMA_HINT + _EVIDENCE_RULE
)
_REDUCE_SYS = (
    "너는 한국어 커뮤니티 여론 분석가다. 여러 묶음에서 나온 부분 분석(JSON)들을 하나의 최종 "
    "리포트로 종합한다. 같은 내용은 합치되 각 항목의 근거 글 번호(post_nos)는 모두 보존해 "
    "합집합으로 둔다. JSON으로만 반환한다: " + _SCHEMA_HINT + _EVIDENCE_RULE
)


def _parse_keywords(raw: str) -> list[str]:
    """Split a keyword string into terms.

    Accepts separators: comma, ``|``, and the word ``or``/``OR`` used as a
    standalone token. ``"에덴 or 오브, 젬"`` -> ``["에덴", "오브", "젬"]``.
    Order preserved, duplicates removed, blanks dropped.
    """
    parts = re.split(r"\s*(?:,|\||\bor\b|\bOR\b)\s*", raw or "")
    seen, out = set(), []
    for p in parts:
        p = p.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip().replace("\r", " ")
    return text[:n] + "…" if len(text) > n else text


def _fetch_comments(db_path, post_nos: list[int]) -> dict[int, list[str]]:
    if not post_nos:
        return {}
    ph = ",".join("?" * len(post_nos))
    out: dict[int, list[str]] = {}
    with db.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT post_no, content FROM comments WHERE post_no IN ({ph}) "
            "ORDER BY post_no, comment_no", post_nos,
        ).fetchall()
    for r in rows:
        out.setdefault(r["post_no"], []).append(r["content"] or "")
    return out


def _build_docs(db_path, keywords: list[str], include_comments: bool, filters: dict,
                max_posts: int) -> tuple[list[str], dict, int]:
    """Return (document blocks, post_no->meta, total_matched_before_cap)."""
    posts = db.load_posts(db_path, exclude_adult=True, q=keywords, **filters)
    if posts.empty:
        return [], {}, 0
    if "recommend" in posts:
        posts = posts.sort_values("recommend", ascending=False)
    total = len(posts)
    posts = posts.head(max_posts)
    post_nos = [int(x) for x in posts["post_no"].tolist()]
    comments = _fetch_comments(db_path, post_nos) if include_comments else {}

    docs, meta = [], {}
    for _, row in posts.iterrows():
        no = int(row["post_no"])
        meta[no] = {"post_no": no, "title": row.get("title") or "",
                    "url": row.get("url") or "", "recommend": int(row.get("recommend") or 0)}
        block = [f"[글 #{no}] 제목: {_truncate(row.get('title'), 150)} "
                 f"(추천 {meta[no]['recommend']})"]
        body = _truncate(row.get("body_text"), _BODY_CHARS)
        if body:
            block.append(f"본문: {body}")
        cmts = comments.get(no, [])[:_MAX_CMTS]
        if cmts:
            block.append("댓글:")
            block += [f"- {_truncate(c, _CMT_CHARS)}" for c in cmts if c.strip()]
        docs.append("\n".join(block))
    return docs, meta, total


def _batch(docs: list[str]) -> list[str]:
    """Group document blocks into batches under the char budget."""
    batches, cur, size = [], [], 0
    for d in docs:
        if cur and size + len(d) > _BATCH_CHARS:
            batches.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(d)
        size += len(d)
    if cur:
        batches.append("\n\n".join(cur))
    return batches


def _sources(post_nos, meta: dict) -> list[dict]:
    """Map a list of post numbers to citation objects (known posts only)."""
    out, seen = [], set()
    for p in post_nos or []:
        try:
            p = int(p)
        except (TypeError, ValueError):
            continue
        if p in meta and p not in seen:
            seen.add(p)
            out.append({"post_no": p, "url": meta[p]["url"], "title": meta[p]["title"]})
    return out


def _norm_findings(items, meta: dict) -> list[dict]:
    """Normalize positives/negatives/issues to ``{text, sources[]}``.

    Tolerates the model returning either plain strings or ``{text, post_nos}``.
    """
    out = []
    for it in items or []:
        if isinstance(it, dict):
            text = it.get("text") or it.get("point") or it.get("content") or ""
            pnos = it.get("post_nos") or ([it["post_no"]] if it.get("post_no") else [])
        else:
            text, pnos = str(it), []
        if text:
            out.append({"text": text, "sources": _sources(pnos, meta)})
    return out


def _norm_themes(items, meta: dict) -> list[dict]:
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append({"title": it.get("title") or "", "detail": it.get("detail") or "",
                        "sources": _sources(it.get("post_nos"), meta)})
        else:
            out.append({"title": str(it), "detail": "", "sources": []})
    return out


def _norm_quotes(items, meta: dict) -> list[dict]:
    out = []
    for q in items or []:
        if not isinstance(q, dict):
            continue
        no = q.get("post_no")
        m = meta.get(int(no)) if str(no).lstrip("-").isdigit() else None
        out.append({"quote": q.get("quote") or "", "post_no": no,
                    "url": m["url"] if m else None, "title": m["title"] if m else None})
    return out


def _normalize(report: dict, meta: dict) -> dict:
    report["themes"] = _norm_themes(report.get("themes"), meta)
    report["positives"] = _norm_findings(report.get("positives"), meta)
    report["negatives"] = _norm_findings(report.get("negatives"), meta)
    report["issues"] = _norm_findings(report.get("issues"), meta)
    report["quotes"] = _norm_quotes(report.get("quotes"), meta)
    return report


# ---- cache -----------------------------------------------------------------
def _ensure_cache(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_reports ("
        "cache_key TEXT PRIMARY KEY, keyword TEXT, model TEXT, source TEXT, "
        "post_count INTEGER, created_at TEXT, report_json TEXT)"
    )


def _cache_key(keywords, model, source, filters, post_nos) -> str:
    payload = json.dumps({"k": sorted(keywords), "m": model, "s": source,
                          "f": filters, "p": sorted(post_nos)}, ensure_ascii=False,
                         sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def keyword_report(db_path: str | Path = db.DEFAULT_DB, *, keyword: str,
                   source: str = "post_comment", refresh: bool = False,
                   max_posts: int = _DEFAULT_MAX_POSTS, model: str | None = None,
                   include_context: bool = False, **filters) -> dict:
    """Build (or fetch cached) an LLM report for one or more keywords.

    ``keyword`` may contain several terms separated by ``,``, ``|`` or ``or`` —
    a post matches if it contains ANY of them. ``source``: ``post_comment``
    (posts + comments) or ``post`` (posts only). Returns the report fields plus
    ``keyword`` (display), ``keywords`` (list), ``post_count``, ``analyzed_posts``,
    ``truncated`` and ``cached`` bookkeeping. Each finding carries ``sources``.

    ``include_context=True`` also returns ``context`` — the document blocks that
    were actually fed to the LLM. It is attached only at return time so it never
    enters the report cache.
    """
    keywords = _parse_keywords(keyword)
    if not keywords:
        return {"error": "키워드를 입력하세요.", "keyword": keyword}
    display = " OR ".join(keywords)

    include_comments = source != "post"
    mdl = model or llm.model_name()
    docs, meta, total = _build_docs(db_path, keywords, include_comments, filters, max_posts)
    if not docs:
        empty = {"keyword": display, "keywords": keywords, "post_count": 0,
                 "analyzed_posts": 0, "truncated": False, "cached": False, "empty": True,
                 "overview": "해당 키워드가 포함된 글이 없습니다.", "mood": "",
                 "themes": [], "positives": [], "negatives": [], "issues": [], "quotes": []}
        if include_context:
            empty["context"] = []
        return empty

    post_nos = list(meta.keys())
    key = _cache_key(keywords, mdl, source, filters, post_nos)

    with db.connect(db_path) as conn:
        _ensure_cache(conn)
        if not refresh:
            row = conn.execute("SELECT report_json FROM llm_reports WHERE cache_key = ?",
                               (key,)).fetchone()
            if row:
                cached = json.loads(row["report_json"])
                cached["cached"] = True
                if include_context:
                    cached["context"] = docs
                return cached

    if not llm.available():
        st = llm.status()
        return {"keyword": display, "keywords": keywords, "post_count": total,
                "analyzed_posts": len(docs),
                "error": f"LLM을 사용할 수 없습니다: {st['reason']}", "llm_status": st}

    batches = _batch(docs)
    if len(batches) == 1:
        report = llm.complete_json(_SINGLE_SYS, f"키워드: '{display}'\n\n{batches[0]}",
                                   max_tokens=5000, model=mdl)
    else:
        # generous per-call budgets so a rich batch/reduce summary isn't truncated
        # mid-JSON (truncation is the main cause of unparseable output here).
        partials = []
        for i, b in enumerate(batches):
            partials.append(llm.complete_json(
                _MAP_SYS, f"키워드: '{display}' (묶음 {i + 1}/{len(batches)})\n\n{b}",
                max_tokens=3500, model=mdl))
        report = llm.complete_json(
            _REDUCE_SYS,
            f"키워드: '{display}'\n\n부분 분석 결과들(JSON):\n{json.dumps(partials, ensure_ascii=False)}",
            max_tokens=6000, model=mdl)

    if not isinstance(report, dict):
        report = {"overview": str(report)}
    report = _normalize(report, meta)
    report.update({
        "keyword": display, "keywords": keywords, "model": mdl, "source": source,
        "post_count": total, "analyzed_posts": len(docs),
        "truncated": total > len(docs), "cached": False,
    })

    with db.connect(db_path) as conn:
        _ensure_cache(conn)
        conn.execute(
            "INSERT OR REPLACE INTO llm_reports "
            "(cache_key, keyword, model, source, post_count, created_at, report_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (key, display, mdl, source, total,
             datetime.now().isoformat(timespec="seconds"),
             json.dumps(report, ensure_ascii=False)),
        )
        conn.commit()
    if include_context:      # after the cache write — context must not be cached
        report["context"] = docs
    return report
