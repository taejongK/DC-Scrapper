from dc_scraper.parse_view import parse_view


def test_extracts_esno(view_html):
    view = parse_view(view_html)
    assert view["e_s_n_o"]
    assert all(c in "0123456789abcdef" for c in view["e_s_n_o"])


def test_extracts_body(view_html):
    view = parse_view(view_html)
    assert view["body_text"].strip()
    assert view["body_html"].strip()


def test_counts_are_ints(view_html):
    view = parse_view(view_html)
    for key in ("recommend", "dislike", "view_count"):
        assert isinstance(view[key], int)


def test_normal_post_not_adult(view_html):
    assert parse_view(view_html)["is_adult"] is False


def test_adult_gate_detected(adult_html):
    view = parse_view(adult_html)
    assert view["is_adult"] is True
    assert view["body_text"] == ""
    assert view["e_s_n_o"] is None
