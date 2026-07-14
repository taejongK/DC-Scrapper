from analysis import keywords, stats, timeseries, trends


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


def test_keywords_extracts_nouns(sample_db):
    kw = {k["word"]: k["count"] for k in keywords.word_frequency(sample_db, source="all", top_n=50)}
    # '캐릭터' appears in post 1 body; adult post body excluded
    assert any("캐릭터" == w for w in kw) or any("에덴" == w for w in kw)


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


def test_heatmap_shape(sample_db):
    hm = timeseries.heatmap(sample_db)
    assert hm["weekdays"] == ["월", "화", "수", "목", "금", "토", "일"]
    assert len(hm["matrix"]) == 7 and all(len(r) == 24 for r in hm["matrix"])
    # post 1: 2026-07-08 (Wed) 09:00 -> matrix[2][9] >= 1
    assert hm["matrix"][2][9] >= 1


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
