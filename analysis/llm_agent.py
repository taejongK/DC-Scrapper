"""Deep report over the corpus, driven by an agentic keyword-discovery pass.

The user asks a free-form question; the LLM first *explores* the corpus with
``search_posts`` / ``get_post`` (a thin tool-calling loop, ``llm.run_tools`` — no
agent framework) to discover the best search terms, **including the community's
slang / synonyms / spelling variants** mined from the actual hits (esp. comments).
Those terms then feed ``llm_report.keyword_report`` — the exhaustive map-reduce
engine — to produce a structured report (개요/분위기/주제/긍정/부정/쟁점/인용) with
evidence links. Every question + report is logged to ``qa_log``.

This is single-turn by design (a report, not a conversation). It supersedes the
old standalone keyword report: same structured output, plus slang-aware retrieval.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import db, llm, llm_report
from .llm_report import _fetch_comments, _parse_keywords, _truncate

_SEARCH_LIMIT = 15
_MAX_SEARCH_LIMIT = 30
_BODY_CHARS = 1500
_COMMENT_PREVIEW_POSTS = 8   # how many top hits show comment previews (slang source)

_DISCOVER_SYS = (
    "너는 디시인사이드 커뮤니티 데이터에서 '검색어를 발굴'하는 에이전트다. 사용자 질문의 "
    "여론을 빠짐없이 조사하려면 어떤 키워드로 검색해야 하는지 찾는 것이 네 임무다. 질문에 "
    "직접 답하지 마라.\n"
    "방법:\n"
    "- search_posts로 질문의 표준어를 먼저 검색하고, 필요하면 get_post로 본문·댓글을 확인하라.\n"
    "- 【핵심】 커뮤니티는 표준어 대신 은어·줄임말·표기변형을 쓴다. 검색 결과의 제목·본문·'댓글'에서 "
    "같은 대상을 가리키는 실제 은어·동의어·표기변형(정식명↔줄임말↔영문표기)을 찾아내라. "
    "1차 결과가 적거나 비어도 부분 힌트에서 은어를 유추해 재검색하라.\n"
    "- 여러 번 검색해 충분히 후보를 모은 뒤, 이 주제를 포괄하는 최종 검색 키워드들을 골라라.\n"
    "출력: 다른 설명 없이 검색 키워드 배열(JSON)만 반환하라. "
    '예: ["젬이오", "젬", "gemini", "제미"]. 5~8개 이내로 핵심만.'
)

_TOOLS = [
    {
        "name": "search_posts",
        "description": (
            "키워드로 글을 검색해 목록(글번호·날짜·추천·댓글수·제목·본문요약·댓글 미리보기)을 "
            "돌려준다. 댓글 미리보기에는 커뮤니티 은어가 자주 담기니, 이를 보고 추가 검색어를 "
            "만들어 확장 검색하는 데 활용하라. 여러 번 호출해도 된다."),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "검색 핵심어. 공백/쉼표로 여러 개 가능(하나라도 포함하면 매칭)."},
                "date_from": {"type": "string", "description": "YYYY-MM-DD, 이 날짜 이후 글만(선택)"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD, 이 날짜 이전 글만(선택)"},
                "sort": {"type": "string", "enum": ["recommend", "latest", "comments"], "description": "정렬 기준(기본 recommend)"},
                "limit": {"type": "integer", "description": "최대 글 수(기본 15, 최대 30)"},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "get_post",
        "description": "특정 글의 전체 본문과 댓글을 가져온다. 검색 결과에서 더 깊이 볼 글이 있을 때 사용.",
        "parameters": {
            "type": "object",
            "properties": {"post_no": {"type": "integer", "description": "글 번호"}},
            "required": ["post_no"],
        },
    },
]


def _record(seen: dict, post_no: int, url, title) -> None:
    seen.setdefault(int(post_no), {"post_no": int(post_no),
                                   "url": url or "", "title": title or ""})


def _tool_search(db_path, args: dict, base: dict, seen: dict) -> str:
    kws = _parse_keywords(str(args.get("keywords") or ""))
    if not kws:
        return "검색어가 비었습니다. keywords를 지정하세요."
    filters = {
        "gallery_id": base.get("gallery_id"),
        "date_from": args.get("date_from") or base.get("date_from"),
        "date_to": args.get("date_to") or base.get("date_to"),
    }
    posts = db.load_posts(db_path, exclude_adult=True, q=kws, **filters)
    if posts.empty:
        return f"'{' / '.join(kws)}' 관련 글을 찾지 못했습니다."
    total = len(posts)
    sort = args.get("sort") or "recommend"
    col = {"latest": "posted_at", "comments": "comment_cnt", "recommend": "recommend"}.get(sort, "recommend")
    if col in posts:
        posts = posts.sort_values(col, ascending=False)
    limit = max(1, min(int(args.get("limit") or _SEARCH_LIMIT), _MAX_SEARCH_LIMIT))
    posts = posts.head(limit)
    # Comments are where community slang/은어 lives — surface a couple per post so
    # the agent can mine real vernacular from the hits and expand its next search.
    nos = [int(r["post_no"]) for _, r in posts.iterrows()]
    cmts = _fetch_comments(db_path, nos[:_COMMENT_PREVIEW_POSTS])
    lines = [f"'{' / '.join(kws)}' 매칭 {total}글 중 상위 {len(posts)}글 ({sort} 정렬):"]
    for _, r in posts.iterrows():
        no = int(r["post_no"])
        _record(seen, no, r.get("url"), r.get("title"))
        body = _truncate(r.get("body_text"), 160)
        head = (f"[글 #{no}] {str(r.get('posted_at'))[:16]} "
                f"추천{int(r.get('recommend') or 0)} 댓{int(r.get('comment_cnt') or 0)} | "
                f"{_truncate(r.get('title'), 100)}")
        line = head + (f" | {body}" if body else "")
        preview = [_truncate(c, 50) for c in cmts.get(no, [])[:2] if c.strip()]
        if preview:
            line += "  · 댓글: " + " / ".join(preview)
        lines.append(line)
    return "\n".join(lines)


def _tool_get_post(db_path, args: dict, seen: dict) -> str:
    try:
        no = int(args.get("post_no"))
    except (TypeError, ValueError):
        return "post_no가 올바르지 않습니다."
    with db.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM posts WHERE post_no = ?", (no,)).fetchone()
    if row is None:
        return f"글 #{no}를 찾지 못했습니다."
    _record(seen, no, row["url"], row["title"])
    cmts = _fetch_comments(db_path, [no]).get(no, [])[:20]
    out = [f"[글 #{no}] {_truncate(row['title'], 150)} "
           f"(추천 {row['recommend'] or 0}, 댓글 {row['comment_cnt'] or 0})",
           f"본문: {_truncate(row['body_text'], _BODY_CHARS)}"]
    if cmts:
        out.append("댓글:")
        out += [f"- {_truncate(c, 180)}" for c in cmts if c.strip()]
    return "\n".join(out)


def _parse_term_list(text: str) -> list[str]:
    """Pull a JSON array of keywords out of the discovery agent's final text."""
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if m:
        try:
            arr = json.loads(m.group(0))
            terms = [str(t).strip() for t in arr if str(t).strip()]
            if terms:
                # dedupe, preserve order, cap
                seen, out = set(), []
                for t in terms:
                    if t.lower() not in seen:
                        seen.add(t.lower())
                        out.append(t)
                return out[:8]
        except (ValueError, json.JSONDecodeError):
            pass
    return []


def discover_keywords(db_path: str | Path, question: str, base: dict,
                      max_turns: int = 6, model: str | None = None) -> list[str]:
    """Agentically explore the corpus to find the best search terms (incl. slang).

    Falls back to the question's own keywords if the agent yields nothing usable.
    """
    throwaway: dict[int, dict] = {}

    def dispatch(name: str, args: dict) -> str:
        try:
            if name == "search_posts":
                return _tool_search(db_path, args, base, throwaway)
            if name == "get_post":
                return _tool_get_post(db_path, args, throwaway)
            return f"알 수 없는 툴: {name}"
        except Exception as exc:  # noqa: BLE001
            return f"툴 실행 오류: {exc}"

    raw = llm.run_tools(_DISCOVER_SYS, f"질문: {question}", _TOOLS, dispatch,
                        max_turns=max_turns, max_tokens=800, model=model)
    terms = _parse_term_list(raw)
    if terms:
        return terms
    # fallback: the question's own comma/or-separated terms, else its words
    fallback = _parse_keywords(question)
    if len(fallback) == 1 and " " in fallback[0]:
        fallback = [w for w in re.split(r"\s+", fallback[0]) if len(w) >= 2]
    return fallback[:8]


def deep_report(db_path: str | Path = db.DEFAULT_DB, *, question: str,
                max_turns: int = 6, max_posts: int = 60, model: str | None = None,
                **filters) -> dict:
    """Slang-aware structured deep report for a free-form question.

    1) agentically discover search terms (incl. community slang), 2) run the
    exhaustive map-reduce keyword report over them, 3) log the Q&A. Returns the
    structured report augmented with ``question`` and ``search_terms``, or
    ``{error, ...}``.
    """
    q = (question or "").strip()
    if not q:
        return {"error": "질문을 입력하세요.", "question": question}
    if not llm.available():
        st = llm.status()
        return {"error": f"LLM을 사용할 수 없습니다: {st['reason']}",
                "llm_status": st, "question": q}

    base = {k: filters.get(k) for k in ("gallery_id", "date_from", "date_to")}
    try:
        terms = discover_keywords(db_path, q, base, max_turns=max_turns, model=model)
        if not terms:
            return {"question": q, "search_terms": [], "empty": True, "post_count": 0,
                    "analyzed_posts": 0, "overview": "검색어를 찾지 못했습니다.",
                    "themes": [], "positives": [], "negatives": [], "issues": [], "quotes": []}
        report = llm_report.keyword_report(
            db_path, keyword=" or ".join(terms), source="post_comment",
            max_posts=max_posts, model=model, include_context=True, **base)
    except llm.LLMError as exc:
        return {"error": str(exc), "question": q}

    # the retrieved context is logged for later inspection, but kept out of the
    # live response (it can be tens of KB)
    context = report.pop("context", None)
    report["question"] = q
    report["search_terms"] = terms
    _log_qa(db_path, report, base, model or llm.model_name(), context=context)
    return report


# ---- Q&A history log -------------------------------------------------------
# Stores, per report: the question, the retrieved `context` actually fed to the
# LLM, and the answer (`report` = full structured JSON; `answer` = its overview,
# kept for cheap list previews).
def _ensure_log(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS qa_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, question TEXT, "
        "answer TEXT, citations TEXT, filters TEXT, model TEXT, used_posts INTEGER, "
        "context TEXT, report TEXT)"
    )
    # additive migration for logs created before context/report existed
    cols = {r[1] for r in conn.execute("PRAGMA table_info(qa_log)").fetchall()}
    for col in ("context", "report"):
        if col not in cols:
            conn.execute(f"ALTER TABLE qa_log ADD COLUMN {col} TEXT")


def _report_sources(report: dict) -> list[dict]:
    """Flatten the report's evidence posts into a deduped citation list."""
    out, seen = [], set()
    for key in ("themes", "positives", "negatives", "issues"):
        for it in report.get(key) or []:
            for s in it.get("sources") or []:
                if s.get("post_no") not in seen:
                    seen.add(s.get("post_no"))
                    out.append(s)
    for q in report.get("quotes") or []:
        no = q.get("post_no")
        if no is not None and no not in seen and q.get("url"):
            seen.add(no)
            out.append({"post_no": no, "url": q.get("url"), "title": q.get("title")})
    return out


def _log_qa(db_path, report: dict, filters: dict, model: str,
            context: list[str] | None = None) -> None:
    """Record one report (question + context + answer). Best-effort — never breaks it."""
    try:
        flt = dict(filters)
        flt["search_terms"] = report.get("search_terms", [])
        with db.connect(db_path) as conn:
            _ensure_log(conn)
            conn.execute(
                "INSERT INTO qa_log (created_at, question, answer, citations, "
                "filters, model, used_posts, context, report) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 report.get("question", ""), report.get("overview", ""),
                 json.dumps(_report_sources(report), ensure_ascii=False),
                 json.dumps({k: v for k, v in flt.items() if v}, ensure_ascii=False),
                 model, report.get("post_count", 0),
                 "\n\n".join(context) if context else None,
                 json.dumps(report, ensure_ascii=False)))
            conn.commit()
    except Exception:  # noqa: BLE001 - logging is non-critical
        pass


def recent_questions(db_path: str | Path = db.DEFAULT_DB, *, limit: int = 20) -> list[dict]:
    """Most recent Q&A log entries, newest first (citations parsed back to list)."""
    try:
        with db.connect(db_path) as conn:
            _ensure_log(conn)
            rows = conn.execute(
                "SELECT id, created_at, question, answer, citations, model, used_posts "
                "FROM qa_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
            ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in rows:
        d = dict(r)
        d["citations"] = json.loads(d.get("citations") or "[]")
        out.append(d)
    return out


def get_logged_report(db_path: str | Path = db.DEFAULT_DB, *, log_id: int) -> dict | None:
    """One logged report in full: question + retrieved context + answer.

    ``report`` is the structured answer (re-renderable); ``context`` is the raw
    document blocks that were fed to the LLM. Returns None if the id is unknown.
    """
    try:
        with db.connect(db_path) as conn:
            _ensure_log(conn)
            row = conn.execute(
                "SELECT id, created_at, question, answer, citations, filters, model, "
                "used_posts, context, report FROM qa_log WHERE id = ?", (int(log_id),)
            ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if row is None:
        return None
    d = dict(row)
    d["citations"] = json.loads(d.get("citations") or "[]")
    d["filters"] = json.loads(d.get("filters") or "{}")
    d["report"] = json.loads(d["report"]) if d.get("report") else None
    # older rows predate context/report capture
    d["context"] = d.get("context") or ""
    return d
