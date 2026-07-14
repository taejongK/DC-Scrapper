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


def _cmt(post_no, comment_no):
    return {
        "post_no": post_no, "comment_no": comment_no, "parent_no": None,
        "writer": "w", "writer_ip": "1.2", "content": "hi",
        "posted_at": "07.09 08:00:00", "is_reply": 0,
        "scraped_at": "2026-07-09 09:00:00",
    }


def test_prune_comments_removes_vanished(tmp_path):
    db = Database(tmp_path / "t.db")
    for no in (1, 2, 3):
        db.upsert_comment(_cmt(post_no=10, comment_no=no))
    db.upsert_comment(_cmt(post_no=20, comment_no=1))   # different post, untouched
    db.commit()

    # latest fetch of post 10 only saw comments 1 and 3 -> 2 was deleted upstream
    deleted = db.prune_comments(10, [1, 3])
    db.commit()
    assert deleted == 1
    remaining = {r[0] for r in db.conn.execute(
        "SELECT comment_no FROM comments WHERE post_no=10").fetchall()}
    assert remaining == {1, 3}
    # other posts are never touched
    assert db.conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_no=20").fetchone()[0] == 1
    db.close()


def test_prune_comments_empty_wipes_thread(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_comment(_cmt(post_no=10, comment_no=1))
    db.upsert_comment(_cmt(post_no=10, comment_no=2))
    db.commit()
    deleted = db.prune_comments(10, [])   # every comment removed upstream
    db.commit()
    assert deleted == 2
    assert db.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0
    db.close()


def test_delete_posts_cascades_comments(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_post(_post(no=1))
    db.upsert_post(_post(no=2))
    db.upsert_comment(_cmt(post_no=1, comment_no=1))
    db.upsert_comment(_cmt(post_no=2, comment_no=1))
    db.commit()

    n = db.delete_posts([1])
    db.commit()
    assert n == 1
    assert db.count_posts_for_date("2026-07-09") == 1          # post 2 survives
    assert db.conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_no=1").fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_no=2").fetchone()[0] == 1
    assert db.delete_posts([]) == 0                            # no-op on empty
    db.close()


def test_post_nos_in_range(tmp_path):
    db = Database(tmp_path / "t.db")
    dates = {1: "2026-07-08 23:00:00", 2: "2026-07-09 12:00:00",
             3: "2026-07-10 01:00:00"}
    for no, ts in dates.items():
        p = _post(no=no)
        p["posted_at"] = ts
        db.upsert_post(p)
    db.commit()
    assert db.post_nos_in_range("aichatting", "2026-07-09", "2026-07-09") == {2}
    assert db.post_nos_in_range("aichatting", "2026-07-08", "2026-07-10") == {1, 2, 3}
    assert db.post_nos_in_range("other", "2026-07-08", "2026-07-10") == set()
    db.close()
