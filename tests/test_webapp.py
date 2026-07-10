import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(sample_db, monkeypatch):
    monkeypatch.setenv("DC_DB_PATH", sample_db)
    from webapp.main import app
    return TestClient(app)


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "대시보드" in r.text


def test_overview_endpoint(client):
    r = client.get("/api/stats/overview")
    assert r.status_code == 200
    assert r.json()["posts"] == 4


def test_posts_list_and_search(client):
    r = client.get("/api/posts?q=젬")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["post_no"] == 2


def test_posts_sort_and_category(client):
    r = client.get("/api/posts?sort=view_count&order=desc")
    items = r.json()["items"]
    assert items[0]["post_no"] == 3     # 200 views
    r2 = client.get("/api/posts?category=❓질문")
    assert r2.json()["total"] == 1


def test_post_detail_with_comments(client):
    r = client.get("/api/posts/1")
    assert r.status_code == 200
    d = r.json()
    assert d["post"]["title"].startswith("에덴")
    assert len(d["comments"]) == 2


def test_post_detail_404(client):
    assert client.get("/api/posts/9999").status_code == 404


def test_top_invalid_sort_400(client):
    assert client.get("/api/stats/top?by=hack").status_code == 400


def test_timeseries_endpoint(client):
    r = client.get("/api/analysis/timeseries?kind=weekday")
    wd = {x["weekday"]: x["count"] for x in r.json()}
    assert wd["수"] == 2 and wd["목"] == 2


def test_keywords_endpoint(client):
    r = client.get("/api/analysis/keywords?top_n=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sentiment_endpoint(client):
    r = client.get("/api/analysis/sentiment?source=comment")
    assert r.json()["total"] == 4


def test_related_endpoint(client):
    r = client.get("/api/analysis/related?word=에덴&source=all")
    assert r.status_code == 200
    body = r.json()
    assert body["keyword"] == "에덴"
    assert "신드롬" in {x["word"] for x in body["related"]}


def test_related_endpoint_missing_word_400(client):
    assert client.get("/api/analysis/related?word=").status_code == 400


def test_keyword_filtered_overview(client):
    r = client.get("/api/stats/overview?q=신드롬")
    assert r.status_code == 200
    assert r.json()["posts"] == 1


def test_keyword_filtered_sentiment(client):
    r = client.get("/api/analysis/sentiment?source=comment&q=신드롬")
    assert r.status_code == 200
    assert r.json()["total"] == 2   # only post 1's comments


def test_collect_validation(client):
    r = client.post("/api/collect", json={"gallery_id": "x", "date_from": "2026-07-09", "date_to": "2026-07-01"})
    assert r.status_code == 400
