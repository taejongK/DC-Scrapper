import json

from dc_scraper.parse_comment import parse_comment_json


def test_parses_comments(comments_json):
    data = json.loads(comments_json)
    post_no = 356233
    comments = parse_comment_json(data, post_no)
    assert comments, "should parse at least one comment"
    for c in comments:
        assert c["post_no"] == post_no
        assert isinstance(c["comment_no"], int)
        assert "content" in c


def test_top_level_parent_normalized(comments_json):
    data = json.loads(comments_json)
    comments = parse_comment_json(data, 356233)
    top = [c for c in comments if c["is_reply"] == 0]
    assert top
    assert all(c["parent_no"] is None for c in top)


def test_reply_flag(comments_json):
    data = json.loads(comments_json)
    comments = parse_comment_json(data, 356233)
    # reg_date is present as raw 'MM.DD HH:MM:SS'
    assert all(c["posted_at"] for c in comments if c["content"])
