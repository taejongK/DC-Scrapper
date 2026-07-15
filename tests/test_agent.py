"""Tests for the deep-report analysis (no network — tool loop + LLM mocked)."""

import json

import pytest

from analysis import llm, llm_agent


@pytest.fixture
def mock_report(monkeypatch):
    """Mock the discovery tool-loop AND the keyword_report map-reduce LLM."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm.set_tool_loop_override(lambda **kw: '["에덴"]')         # discovered terms
    llm.set_override(lambda **kw: json.dumps({
        "overview": "요약", "mood": "긍정",
        "themes": [{"title": "T", "detail": "d", "post_nos": [1]}],
        "positives": [{"text": "좋다", "post_nos": [1]}],
        "negatives": [], "issues": [], "quotes": [{"quote": "최고", "post_no": 1}],
    }, ensure_ascii=False))
    yield
    llm.set_tool_loop_override(None)
    llm.set_override(None)


# ---- retrieval tools (real, against the sample DB) -------------------------
def test_search_tool_finds_and_records(sample_db):
    seen = {}
    out = llm_agent._tool_search(sample_db, {"keywords": "에덴"}, {}, seen)
    assert "글 #1" in out
    assert 1 in seen and seen[1]["url"] == "http://x/1"
    assert seen[1]["title"].startswith("에덴")


def test_search_tool_includes_comment_preview(sample_db):
    # comments carry slang; search results must surface a preview for expansion
    out = llm_agent._tool_search(sample_db, {"keywords": "에덴"}, {}, {})
    assert "댓글:" in out
    assert "추천" in out  # post 1's comment "나도 좋아 완전 추천" is previewed


def test_search_tool_no_match(sample_db):
    out = llm_agent._tool_search(sample_db, {"keywords": "존재하지않는단어zzz"}, {}, {})
    assert "찾지 못했" in out


def test_search_tool_excludes_adult(sample_db):
    # "지침" appears only in the adult post 3's title -> exclude_adult drops it.
    seen = {}
    out = llm_agent._tool_search(sample_db, {"keywords": "지침"}, {}, seen)
    assert 3 not in seen
    assert "찾지 못했" in out


def test_get_post_tool(sample_db):
    seen = {}
    out = llm_agent._tool_get_post(sample_db, {"post_no": 1}, seen)
    assert "글 #1" in out and "본문:" in out
    assert 1 in seen and "댓글:" in out


def test_get_post_tool_missing(sample_db):
    assert "찾지 못했" in llm_agent._tool_get_post(sample_db, {"post_no": 9999}, {})


# ---- keyword-discovery parsing ---------------------------------------------
def test_parse_term_list():
    assert llm_agent._parse_term_list('["젬","gemini"]') == ["젬", "gemini"]
    assert llm_agent._parse_term_list('설명 ["a","b"] 끝') == ["a", "b"]
    assert llm_agent._parse_term_list("배열 없음") == []
    assert llm_agent._parse_term_list('["a","A","a"]') == ["a"]   # case-insensitive dedup


def test_discover_keywords_fallback(sample_db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm.set_tool_loop_override(lambda **kw: "그냥 텍스트, JSON 배열 없음")
    terms = llm_agent.discover_keywords(sample_db, "에덴 신드롬", {})
    llm.set_tool_loop_override(None)
    assert terms == ["에덴", "신드롬"]   # falls back to the question's own keywords


# ---- deep report -----------------------------------------------------------
def test_deep_report_discovers_and_reports(sample_db, mock_report):
    r = llm_agent.deep_report(sample_db, question="에덴 여론?")
    assert r["question"] == "에덴 여론?"
    assert r["search_terms"] == ["에덴"]
    assert r["overview"] == "요약"
    assert r["post_count"] == 1
    assert r["positives"][0]["sources"][0]["post_no"] == 1


def test_deep_report_logs_to_db(sample_db, mock_report):
    llm_agent.deep_report(sample_db, question="에덴 여론?", gallery_id="aichatting")
    hist = llm_agent.recent_questions(sample_db)
    assert hist[0]["question"] == "에덴 여론?"
    assert hist[0]["answer"] == "요약"                 # overview logged
    assert hist[0]["citations"][0]["post_no"] == 1     # evidence flattened
    assert hist[0]["used_posts"] == 1                  # post_count


def test_deep_report_logs_context_and_full_report(sample_db, mock_report):
    r = llm_agent.deep_report(sample_db, question="에덴 여론?")
    assert "context" not in r          # kept out of the live response (can be huge)
    hist = llm_agent.recent_questions(sample_db)
    d = llm_agent.get_logged_report(sample_db, log_id=hist[0]["id"])
    assert d["question"] == "에덴 여론?"
    assert "[글 #1]" in d["context"]    # the documents actually fed to the LLM
    assert d["report"]["overview"] == "요약"          # full structured answer
    assert d["report"]["positives"][0]["text"] == "좋다"
    assert d["filters"]["search_terms"] == ["에덴"]


def test_recent_questions_list_is_lean(sample_db, mock_report):
    llm_agent.deep_report(sample_db, question="에덴 여론?")
    row = llm_agent.recent_questions(sample_db)[0]
    assert "context" not in row and "report" not in row   # list stays small
    assert row["answer"] == "요약"                        # overview preview


def test_get_logged_report_missing(sample_db):
    assert llm_agent.get_logged_report(sample_db, log_id=9999) is None


def test_recent_questions_newest_first(sample_db, mock_report):
    llm_agent.deep_report(sample_db, question="첫번째")
    llm_agent.deep_report(sample_db, question="두번째")
    hist = llm_agent.recent_questions(sample_db, limit=5)
    assert hist[0]["question"] == "두번째" and hist[1]["question"] == "첫번째"


def test_deep_report_empty_question(sample_db):
    assert llm_agent.deep_report(sample_db, question="   ")["error"]


def test_deep_report_unavailable(sample_db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = llm_agent.deep_report(sample_db, question="에덴 여론?")
    assert "error" in r and "llm_status" in r


def test_failed_report_not_logged(sample_db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    llm_agent.deep_report(sample_db, question="키없음")   # error, no log
    assert all(h["question"] != "키없음" for h in llm_agent.recent_questions(sample_db))


# ---- API -------------------------------------------------------------------
@pytest.fixture
def client(sample_db, monkeypatch):
    monkeypatch.setenv("DC_DB_PATH", sample_db)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from fastapi.testclient import TestClient

    from webapp.main import app
    yield TestClient(app)
    llm.set_tool_loop_override(None)
    llm.set_override(None)


def test_api_ask(client, mock_report):
    r = client.post("/api/analysis/ask", json={"question": "에덴 여론 어때?"})
    assert r.status_code == 200
    body = r.json()
    assert body["overview"] == "요약"
    assert body["search_terms"] == ["에덴"]
    assert body["positives"][0]["sources"][0]["post_no"] == 1


def test_api_ask_validation(client):
    assert client.post("/api/analysis/ask", json={"question": "  "}).status_code == 400


def test_api_ask_history(client, mock_report):
    client.post("/api/analysis/ask", json={"question": "기록되나?"})
    r = client.get("/api/analysis/ask_history?limit=5")
    assert r.status_code == 200
    assert r.json()[0]["question"] == "기록되나?"


def test_api_ask_history_detail(client, mock_report):
    client.post("/api/analysis/ask", json={"question": "상세보기?"})
    log_id = client.get("/api/analysis/ask_history?limit=1").json()[0]["id"]
    d = client.get(f"/api/analysis/ask_history/{log_id}").json()
    assert d["question"] == "상세보기?"
    assert "[글 #1]" in d["context"]                # 검색된 context
    assert d["report"]["overview"] == "요약"        # answer (구조화 전체)


def test_api_ask_history_detail_404(client):
    assert client.get("/api/analysis/ask_history/99999").status_code == 404
