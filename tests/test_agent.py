"""Tests for the agentic Q&A analysis (no network — the tool loop is mocked)."""

import pytest

from analysis import llm, llm_agent


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield
    llm.set_tool_loop_override(None)


# ---- retrieval tools (real, against the sample DB) -------------------------
def test_search_tool_finds_and_records(sample_db):
    seen = {}
    out = llm_agent._tool_search(sample_db, {"keywords": "에덴"}, {}, seen)
    assert "글 #1" in out
    assert 1 in seen and seen[1]["url"] == "http://x/1"
    assert seen[1]["title"].startswith("에덴")


def test_search_tool_no_match(sample_db):
    out = llm_agent._tool_search(sample_db, {"keywords": "존재하지않는단어zzz"}, {}, {})
    assert "찾지 못했" in out


def test_search_tool_excludes_adult(sample_db):
    # "지침" appears only in the adult post 3's title -> exclude_adult drops it,
    # so the search finds nothing and never records post 3.
    seen = {}
    out = llm_agent._tool_search(sample_db, {"keywords": "지침"}, {}, seen)
    assert 3 not in seen
    assert "찾지 못했" in out


def test_get_post_tool(sample_db):
    seen = {}
    out = llm_agent._tool_get_post(sample_db, {"post_no": 1}, seen)
    assert "글 #1" in out and "본문:" in out
    assert 1 in seen
    # post 1 has 2 comments in the fixture -> comment section present
    assert "댓글:" in out


def test_get_post_tool_missing(sample_db):
    assert "찾지 못했" in llm_agent._tool_get_post(sample_db, {"post_no": 9999}, {})


# ---- agent loop ------------------------------------------------------------
def test_answer_question_cites_searched_posts(sample_db, with_key):
    def fake_loop(**kw):
        # the agent searches, then answers citing post #1
        kw["dispatch"]("search_posts", {"keywords": "에덴"})
        return "에덴 신드롬 반응은 대체로 긍정적이다 [#1]."

    llm.set_tool_loop_override(fake_loop)
    r = llm_agent.answer_question(sample_db, question="에덴 여론 어때?")
    assert r["answer"].startswith("에덴")
    assert r["used_posts"] == 1
    assert r["empty"] is False
    assert r["citations"][0]["post_no"] == 1
    assert r["citations"][0]["url"] == "http://x/1"


def test_answer_question_only_cites_referenced(sample_db, with_key):
    def fake_loop(**kw):
        kw["dispatch"]("search_posts", {"keywords": "이", "limit": 30})  # sees several
        return "특별히 언급할 게 없다."                                    # cites none

    llm.set_tool_loop_override(fake_loop)
    r = llm_agent.answer_question(sample_db, question="아무거나")
    assert r["used_posts"] >= 1          # tool did surface posts
    assert r["citations"] == []          # but none were referenced in the answer


def test_answer_question_empty_question(sample_db):
    assert llm_agent.answer_question(sample_db, question="   ")["error"]


def test_answer_question_unavailable(sample_db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = llm_agent.answer_question(sample_db, question="에덴 여론?")
    assert "error" in r and "llm_status" in r


# ---- API -------------------------------------------------------------------
@pytest.fixture
def client(sample_db, monkeypatch):
    monkeypatch.setenv("DC_DB_PATH", sample_db)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from fastapi.testclient import TestClient

    from webapp.main import app
    yield TestClient(app)
    llm.set_tool_loop_override(None)


def test_api_ask(client):
    llm.set_tool_loop_override(
        lambda **kw: (kw["dispatch"]("search_posts", {"keywords": "에덴"}),
                      "에덴 반응은 긍정적 [#1]")[1])
    r = client.post("/api/analysis/ask", json={"question": "에덴 여론 어때?"})
    assert r.status_code == 200
    body = r.json()
    assert "긍정" in body["answer"]
    assert body["citations"][0]["post_no"] == 1


def test_api_ask_validation(client):
    assert client.post("/api/analysis/ask", json={"question": "  "}).status_code == 400
