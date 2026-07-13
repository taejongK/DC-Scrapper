"""Tests for the LLM deep-analysis feature (no network — the LLM is mocked)."""

import json

import pytest

from analysis import llm, llm_report


# ---- llm wrapper -----------------------------------------------------------
def test_status_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    st = llm.status()
    assert st["available"] is False
    assert st["has_key"] is False
    assert st["reason"]


def test_complete_json_extracts_fenced_and_bare(monkeypatch):
    llm.set_override(lambda **k: "```json\n{\"a\": 1}\n```")
    assert llm.complete_json("s", "u") == {"a": 1}
    llm.set_override(lambda **k: "sure, here: [1, 2, 3] ok")
    assert llm.complete_json("s", "u") == [1, 2, 3]
    llm.set_override(None)


def test_complete_json_raises_on_garbage(monkeypatch):
    llm.set_override(lambda **k: "no json at all")
    with pytest.raises(llm.LLMError):
        llm.complete_json("s", "u")
    llm.set_override(None)


# ---- report builder --------------------------------------------------------
@pytest.fixture
def mock_llm(monkeypatch):
    """Install a deterministic LLM that records how many times it was called."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = {"n": 0}

    def fake(**kw):
        calls["n"] += 1
        return json.dumps({
            "overview": "요약문",
            "mood": "대체로 긍정",
            "themes": [{"title": "주제A", "detail": "설명", "post_nos": [1]}],
            "positives": [{"text": "좋다", "post_nos": [1]}],
            "negatives": [{"text": "아쉽다", "post_nos": [1]}],
            "issues": [{"text": "쟁점", "post_nos": [1]}],
            "quotes": [{"quote": "최고야", "post_no": 1}],
        }, ensure_ascii=False)

    llm.set_override(fake)
    yield calls
    llm.set_override(None)


def test_keyword_report_basic_and_enrichment(sample_db, mock_llm):
    r = llm_report.keyword_report(sample_db, keyword="에덴", source="post_comment")
    assert r["keyword"] == "에덴" and r["keywords"] == ["에덴"]
    assert r["post_count"] == 1 and r["analyzed_posts"] == 1
    assert r["overview"] == "요약문"
    assert r["cached"] is False
    # quote for post_no 1 gets its url/title attached
    q = r["quotes"][0]
    assert q["post_no"] == 1 and q["url"] == "http://x/1"
    assert q["title"].startswith("에덴")
    # each finding carries evidence sources with the post's url
    pos = r["positives"][0]
    assert pos["text"] == "좋다"
    assert pos["sources"][0]["post_no"] == 1 and pos["sources"][0]["url"] == "http://x/1"
    assert r["themes"][0]["sources"][0]["post_no"] == 1
    assert mock_llm["n"] == 1


def test_parse_keywords_variants():
    from analysis.llm_report import _parse_keywords
    assert _parse_keywords("에덴 or 오브, 젬") == ["에덴", "오브", "젬"]
    assert _parse_keywords("에덴 | 오브") == ["에덴", "오브"]
    assert _parse_keywords("  에덴  ") == ["에덴"]
    assert _parse_keywords("에덴, 에덴") == ["에덴"]   # dedup
    assert _parse_keywords("   ") == []


def test_keyword_report_multi_keyword_or(sample_db, mock_llm):
    # "에덴"(post1) OR "젬"(post2) -> 2 posts matched
    r = llm_report.keyword_report(sample_db, keyword="에덴 or 젬")
    assert r["keywords"] == ["에덴", "젬"]
    assert r["keyword"] == "에덴 OR 젬"
    assert r["post_count"] == 2


def test_keyword_report_is_cached(sample_db, mock_llm):
    llm_report.keyword_report(sample_db, keyword="에덴")
    assert mock_llm["n"] == 1
    r2 = llm_report.keyword_report(sample_db, keyword="에덴")
    assert r2["cached"] is True
    assert mock_llm["n"] == 1  # no second LLM call
    # refresh bypasses the cache
    r3 = llm_report.keyword_report(sample_db, keyword="에덴", refresh=True)
    assert r3["cached"] is False and mock_llm["n"] == 2


def test_keyword_report_truncation(sample_db, mock_llm):
    # "이" matches posts 1,2,4 (non-adult); cap to 1 -> truncated
    r = llm_report.keyword_report(sample_db, keyword="이", max_posts=1)
    assert r["post_count"] >= 2
    assert r["analyzed_posts"] == 1
    assert r["truncated"] is True


def test_keyword_report_empty_and_nomatch(sample_db, mock_llm):
    assert llm_report.keyword_report(sample_db, keyword="  ")["error"]
    nomatch = llm_report.keyword_report(sample_db, keyword="존재하지않는단어zzz")
    assert nomatch["empty"] is True and nomatch["post_count"] == 0
    assert mock_llm["n"] == 0  # no LLM call when there's nothing to analyze


def test_keyword_report_unavailable_without_key(sample_db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    llm.set_override(None)
    r = llm_report.keyword_report(sample_db, keyword="에덴")
    assert "error" in r and "llm_status" in r


# ---- API -------------------------------------------------------------------
@pytest.fixture
def client(sample_db, monkeypatch):
    monkeypatch.setenv("DC_DB_PATH", sample_db)
    from webapp.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_api_llm_status(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = client.get("/api/analysis/llm_status")
    assert r.status_code == 200 and r.json()["available"] is False


def test_api_llm_report(client, mock_llm):
    r = client.post("/api/analysis/llm_report", json={"q": "에덴", "source": "post_comment"})
    assert r.status_code == 200
    body = r.json()
    assert body["overview"] == "요약문" and body["analyzed_posts"] == 1


def test_api_llm_report_validation(client):
    assert client.post("/api/analysis/llm_report", json={"q": "  "}).status_code == 400
    assert client.post("/api/analysis/llm_report",
                       json={"q": "x", "source": "bad"}).status_code == 400
