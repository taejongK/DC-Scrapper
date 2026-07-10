from dc_scraper.db import Database


def _post(no=1):
    return {
        "post_no": no, "gallery_id": "aichatting", "title": "t", "writer": "w",
        "writer_ip": None, "writer_uid": None, "posted_at": "2026-07-09 08:00:00",
        "view_count": 10, "recommend": 1, "dislike": 0, "comment_cnt": 0,
        "category": "잡담", "body_text": "b", "body_html": "<p>b</p>",
        "url": "http://x", "scraped_at": "2026-07-09 09:00:00",
    }


def test_upsert_post_idempotent(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_post(_post())
    db.upsert_post(_post())          # same post_no again
    db.commit()
    assert db.count_posts_for_date("2026-07-09") == 1

    # update reflected
    p = _post()
    p["view_count"] = 99
    db.upsert_post(p)
    db.commit()
    row = db.conn.execute("SELECT view_count FROM posts WHERE post_no=1").fetchone()
    assert row["view_count"] == 99
    db.close()


def test_upsert_comment_idempotent(tmp_path):
    db = Database(tmp_path / "t.db")
    c = {
        "post_no": 1, "comment_no": 555, "parent_no": None, "writer": "w",
        "writer_ip": "1.2", "content": "hi", "posted_at": "07.09 08:00:00",
        "is_reply": 0, "scraped_at": "2026-07-09 09:00:00",
    }
    db.upsert_comment(c)
    db.upsert_comment(c)
    db.commit()
    n = db.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    assert n == 1
    db.close()
