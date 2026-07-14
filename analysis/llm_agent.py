"""Agentic Q&A over the collected community corpus.

Unlike ``llm_report`` (keyword → fixed-structure report), this lets the user ask
a free-form question. The LLM drives its own retrieval: it calls ``search_posts``
to find relevant posts and ``get_post`` to drill into one, then answers in Korean
citing the post numbers it used (``[#123]``). The loop is a thin tool-calling
cycle (``llm.run_tools``) — no agent framework — bounded by ``max_turns``.

v1 is single-turn (one question → one grounded answer). Multi-turn conversation
is a later phase.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import db, llm
from .llm_report import _fetch_comments, _parse_keywords, _truncate

_SEARCH_LIMIT = 15
_MAX_SEARCH_LIMIT = 30
_BODY_CHARS = 1500

_SYS = (
    "너는 디시인사이드 커뮤니티 수집 데이터를 분석하는 리서치 에이전트다. "
    "사용자의 질문에 답하기 위해 제공된 툴로 글·댓글을 직접 검색하고, 그 근거를 바탕으로 "
    "한국어로 답한다.\n"
    "원칙:\n"
    "- 먼저 search_posts로 관련 글을 찾고, 필요하면 get_post로 본문·댓글을 확인한 뒤 답하라.\n"
    "- 한 번의 검색으로 부족하면 검색어를 바꿔 여러 번 검색하라.\n"
    "- 슬랭·은어·반어를 감안해 실제 뉘앙스를 읽어라.\n"
    "- 답의 각 핵심 주장 옆에 근거가 된 글 번호를 [#글번호] 형식으로 표기하라.\n"
    "- 데이터에서 확인되지 않는 내용은 지어내지 말고 '해당 데이터에서는 확인되지 않는다'고 밝혀라.\n"
    "- 답변은 간결하되, 여론의 갈래(긍정/부정/쟁점)가 있으면 나눠서 정리하라."
)

_TOOLS = [
    {
        "name": "search_posts",
        "description": (
            "키워드로 글을 검색해 목록(글번호·날짜·추천·댓글수·제목·본문요약)을 돌려준다. "
            "여론·화제·평가를 파악하려면 먼저 이 툴로 관련 글을 찾아라."),
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
    lines = [f"'{' / '.join(kws)}' 매칭 {total}글 중 상위 {len(posts)}글 ({sort} 정렬):"]
    for _, r in posts.iterrows():
        no = int(r["post_no"])
        _record(seen, no, r.get("url"), r.get("title"))
        body = _truncate(r.get("body_text"), 160)
        head = (f"[글 #{no}] {str(r.get('posted_at'))[:16]} "
                f"추천{int(r.get('recommend') or 0)} 댓{int(r.get('comment_cnt') or 0)} | "
                f"{_truncate(r.get('title'), 100)}")
        lines.append(head + (f" | {body}" if body else ""))
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


def _referenced_sources(answer: str, seen: dict) -> list[dict]:
    """Citations actually referenced as [#num] in the answer (order preserved)."""
    out, added = [], set()
    for m in re.finditer(r"#(\d+)", answer or ""):
        no = int(m.group(1))
        if no in seen and no not in added:
            added.add(no)
            out.append(seen[no])
    return out


def answer_question(db_path: str | Path = db.DEFAULT_DB, *, question: str,
                    max_turns: int = 6, model: str | None = None,
                    **filters) -> dict:
    """Answer a free-form question about the corpus, with cited evidence.

    ``filters`` (gallery_id / date_from / date_to) scope every search. Returns
    ``{question, answer, citations[], used_posts, empty}`` or ``{error, ...}``.
    """
    q = (question or "").strip()
    if not q:
        return {"error": "질문을 입력하세요.", "question": question}
    if not llm.available():
        st = llm.status()
        return {"error": f"LLM을 사용할 수 없습니다: {st['reason']}",
                "llm_status": st, "question": q}

    base = {k: filters.get(k) for k in ("gallery_id", "date_from", "date_to")}
    seen: dict[int, dict] = {}

    def dispatch(name: str, args: dict) -> str:
        try:
            if name == "search_posts":
                return _tool_search(db_path, args, base, seen)
            if name == "get_post":
                return _tool_get_post(db_path, args, seen)
            return f"알 수 없는 툴: {name}"
        except Exception as exc:  # noqa: BLE001 - feed errors back to the model
            return f"툴 실행 오류: {exc}"

    try:
        answer = llm.run_tools(_SYS, f"질문: {q}", _TOOLS, dispatch,
                               max_turns=max_turns, max_tokens=3000, model=model)
    except llm.LLMError as exc:
        return {"error": str(exc), "question": q}

    return {
        "question": q,
        "answer": answer,
        "citations": _referenced_sources(answer, seen),
        "used_posts": len(seen),
        "empty": len(seen) == 0,
    }
