from analysis import keywords, sentiment, stats, timeseries


def test_overview(sample_db):
    ov = stats.overview(sample_db)
    assert ov["posts"] == 4
    assert ov["comments"] == 4
    assert ov["adult_posts"] == 1
    assert ov["date_from"] == "2026-07-08"
    assert ov["date_to"] == "2026-07-09"


def test_top_posts_by_recommend(sample_db):
    top = stats.top_posts(sample_db, by="recommend", limit=2)
    assert top[0]["post_no"] == 3      # rec 20
    assert top[1]["post_no"] == 1      # rec 10


def test_top_posts_invalid_sort(sample_db):
    import pytest
    with pytest.raises(ValueError):
        stats.top_posts(sample_db, by="nope")


def test_category_distribution(sample_db):
    dist = {d["category"]: d["count"] for d in stats.category_distribution(sample_db)}
    assert dist["💬잡담"] == 1 and dist["📕리뷰"] == 1


def test_exclude_adult_filter(sample_db):
    ov_all = stats.overview(sample_db)
    ov_clean = stats.overview(sample_db, exclude_adult=True)
    assert ov_all["posts"] == 4 and ov_clean["posts"] == 3


def test_keyword_filter_scopes_posts(sample_db):
    # only post 1 ("에덴 신드롬…") contains 신드롬
    ov = stats.overview(sample_db, q="신드롬")
    assert ov["posts"] == 1
    # its 2 comments are included
    assert ov["comments"] == 2


def test_keyword_filter_on_keywords(sample_db):
    kw = {k["word"] for k in keywords.word_frequency(sample_db, source="post", q="신드롬")}
    assert "캐릭터" in kw or "에덴" in kw   # from post 1 only


def test_keyword_filter_no_match(sample_db):
    assert stats.overview(sample_db, q="없는키워드zzz")["posts"] == 0


def test_timeseries_by_date(sample_db):
    d = {r["date"]: r["count"] for r in timeseries.by_date(sample_db)}
    assert d["2026-07-08"] == 2 and d["2026-07-09"] == 2


def test_timeseries_weekday(sample_db):
    wd = {r["weekday"]: r["count"] for r in timeseries.by_weekday(sample_db)}
    # 2026-07-08 = Wed, 2026-07-09 = Thu
    assert wd["수"] == 2 and wd["목"] == 2


def test_timeseries_hour_full_range(sample_db):
    hours = timeseries.by_hour(sample_db)
    assert len(hours) == 24
    by_h = {r["hour"]: r["count"] for r in hours}
    assert by_h[9] == 1 and by_h[22] == 1


def test_keywords_extracts_nouns(sample_db):
    kw = {k["word"]: k["count"] for k in keywords.word_frequency(sample_db, source="all", top_n=50)}
    # '캐릭터' appears in post 1 body; adult post body excluded
    assert any("캐릭터" == w for w in kw) or any("에덴" == w for w in kw)


def test_sentiment_distribution(sample_db):
    s = sentiment.sentiment_distribution(sample_db, source="comment")
    assert s["total"] == 4
    assert s["counts"]["positive"] >= 1   # "좋아 완전 추천", "재밌다"
    assert s["counts"]["negative"] >= 1   # "짜증나고 별로야"


def test_related_words(sample_db):
    # post 1 body "이 캐릭터 정말 좋아 최고야" + title "에덴 신드롬 진짜 좋다"
    r = keywords.related_words(sample_db, keyword="에덴", source="all", top_n=10)
    assert r["keyword"] == "에덴"
    assert r["doc_count"] >= 1
    words = {x["word"] for x in r["related"]}
    assert "신드롬" in words          # co-occurs in the same title
    assert "에덴" not in words         # keyword itself excluded


def test_related_words_empty_keyword(sample_db):
    r = keywords.related_words(sample_db, keyword="  ", source="all")
    assert r["doc_count"] == 0 and r["related"] == []


def test_related_words_absent_keyword(sample_db):
    r = keywords.related_words(sample_db, keyword="존재하지않는단어", source="all")
    assert r["doc_count"] == 0 and r["related"] == []


def test_sentiment_score_text():
    assert sentiment.score_text("이거 진짜 좋고 최고야")["label"] == "positive"
    assert sentiment.score_text("완전 별로고 최악이야")["label"] == "negative"
    assert sentiment.score_text("오늘 밥 먹었다")["label"] == "neutral"
