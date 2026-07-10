from dc_scraper.parse_list import parse_list


def test_excludes_notices(list_html):
    posts = parse_list(list_html)
    # Fixture page has 50 rows: 5 notices (말머리 '공지') + 45 articles.
    assert len(posts) == 45
    assert all(p["category"] != "공지" for p in posts)


def test_all_post_no_are_int(list_html):
    posts = parse_list(list_html)
    assert all(isinstance(p["post_no"], int) for p in posts)


def test_posted_at_is_full_timestamp(list_html):
    posts = parse_list(list_html)
    # title attr holds full 'YYYY-MM-DD HH:MM:SS'
    assert all(len(p["posted_at"]) >= 19 for p in posts)
    assert posts[0]["posted_at"][:4].isdigit()


def test_fields_present(list_html):
    p = parse_list(list_html)[0]
    for key in ("post_no", "gallery_id", "title", "posted_at", "url"):
        assert p[key], f"missing {key}"
    assert p["url"].startswith("https://gall.dcinside.com")
