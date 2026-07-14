from analysis import keywords, sentiment, stats, timeseries, trends


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


def test_keyword_filter_list_or(sample_db):
    from analysis import db as adb
    # "신드롬"(post1) OR "젬"(post2) -> 2 posts
    df = adb.load_posts(sample_db, q=["신드롬", "젬"])
    assert set(df["post_no"]) == {1, 2}
    # single-element list behaves like the string form
    assert set(adb.load_posts(sample_db, q=["신드롬"])["post_no"]) == {1}


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


def test_salient_words_returns_scores(sample_db):
    sal = keywords.salient_words(sample_db, source="post", top_n=20)
    assert sal, "expected at least one salient term"
    top = sal[0]
    assert {"word", "count", "score"} <= set(top)
    # sorted by score descending
    scores = [s["score"] for s in sal]
    assert scores == sorted(scores, reverse=True)


def test_extract_terms_bigrams():
    terms = keywords.extract_terms("에덴 캐릭터 업데이트")
    # adjacent content nouns form bigrams, unigrams kept too
    assert "에덴" in terms and "캐릭터" in terms
    assert "에덴 캐릭터" in terms


def test_extract_nouns_strips_inline_markup():
    # AI-chat users paste HTML/CSS status-window templates into the body as text;
    # the tags, entity refs, and CSS units must not leak in as "nouns".
    text = (
        '캐릭터 상태창 양식임\n'
        '<div style="background:#09090b; border: 2px solid #00e5ff; '
        'padding: 12px; color: #ffffff; font-family: sans-serif;">상태</div>\n'
        '라벨은 최소 60px, 바 높이는 6px로 맞춰줘&nbsp;'
    )
    nouns = set(keywords.extract_nouns(text))
    # real content survives
    assert "캐릭터" in nouns and "상태" in nouns
    # markup / CSS noise is gone
    for junk in ("div", "px", "font", "color", "border", "style", "padding", "background"):
        assert junk not in nouns, f"{junk!r} leaked through markup cleaning"


def test_related_words_pmi_ranks_distinctive(sample_db):
    # 신드롬 co-occurs only with 에덴 (rare) -> high PMI, must appear
    r = keywords.related_words(sample_db, keyword="에덴", source="all", top_n=10)
    words = {x["word"] for x in r["related"]}
    assert "신드롬" in words
    assert all("score" in x for x in r["related"])


def test_heatmap_shape(sample_db):
    hm = timeseries.heatmap(sample_db)
    assert hm["weekdays"] == ["월", "화", "수", "목", "금", "토", "일"]
    assert len(hm["matrix"]) == 7 and all(len(r) == 24 for r in hm["matrix"])
    # post 1: 2026-07-08 (Wed) 09:00 -> matrix[2][9] >= 1
    assert hm["matrix"][2][9] >= 1


def test_engagement_by_date(sample_db):
    eng = {e["date"]: e for e in timeseries.engagement_by_date(sample_db)}
    assert eng["2026-07-08"]["posts"] == 2
    assert eng["2026-07-08"]["views"] == 150      # 100 + 50
    assert eng["2026-07-08"]["recommend"] == 11   # 10 + 1


def test_sentiment_by_date(sample_db):
    rows = {r["date"]: r for r in timeseries.sentiment_by_date(sample_db)}
    # 2026-07-08: post1 positive, post2 negative
    assert rows["2026-07-08"]["positive"] >= 1
    assert rows["2026-07-08"]["negative"] >= 1
    assert "mean_score" in rows["2026-07-08"]


def test_trends_available_dates(sample_db):
    assert trends.available_dates(sample_db) == ["2026-07-08", "2026-07-09"]


def test_trends_daily_bursts_new_keywords(sample_db):
    # 2026-07-09 has post 4 ("질문 있어요 / 이거 어떻게 설정하나요"); 07-08 is baseline
    b = trends.daily_bursts(sample_db, date="2026-07-09", min_count=1)
    assert b["date"] == "2026-07-09"
    assert b["baseline_days"] == 1
    new = {x["word"] for x in b["new_keywords"]}
    assert "질문" in new or "설정" in new
    # every burst entry carries the expected shape
    assert all({"word", "count", "burst", "is_new"} <= set(x) for x in b["bursts"])


def test_trends_empty_baseline_first_day(sample_db):
    b = trends.daily_bursts(sample_db, date="2026-07-08", min_count=1)
    assert b["baseline_days"] == 0
    # with no baseline, every term is "new"
    assert all(x["is_new"] for x in b["bursts"])


def test_sentiment_score_text():
    assert sentiment.score_text("이거 진짜 좋고 최고야")["label"] == "positive"
    assert sentiment.score_text("완전 별로고 최악이야")["label"] == "negative"
    assert sentiment.score_text("오늘 밥 먹었다")["label"] == "neutral"
