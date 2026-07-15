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


_WHEN = "2026-07-10 12:00:00"


def test_mark_comments_deleted_flags_vanished(tmp_path):
    db = Database(tmp_path / "t.db")
    for no in (1, 2, 3):
        db.upsert_comment(_cmt(post_no=10, comment_no=no))
    db.upsert_comment(_cmt(post_no=20, comment_no=1))   # different post, untouched
    db.commit()

    # latest fetch of post 10 only saw comments 1 and 3 -> 2 vanished upstream
    marked = db.mark_comments_deleted(10, [1, 3], _WHEN)
    db.commit()
    assert marked == 1
    # nothing is removed — the archive keeps every comment
    assert db.conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_no=10").fetchone()[0] == 3
    row = db.conn.execute(
        "SELECT is_deleted, deleted_at FROM comments WHERE post_no=10 AND comment_no=2"
    ).fetchone()
    assert row["is_deleted"] == 1 and row["deleted_at"] == _WHEN
    # survivors stay unflagged; other posts are never touched
    kept = db.conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_no=10 AND COALESCE(is_deleted,0)=0"
    ).fetchone()[0]
    assert kept == 2
    assert db.conn.execute(
        "SELECT COALESCE(is_deleted,0) FROM comments WHERE post_no=20").fetchone()[0] == 0
    db.close()


def test_mark_comments_deleted_empty_flags_thread(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_comment(_cmt(post_no=10, comment_no=1))
    db.upsert_comment(_cmt(post_no=10, comment_no=2))
    db.commit()
    marked = db.mark_comments_deleted(10, [], _WHEN)   # all gone upstream
    db.commit()
    assert marked == 2
    assert db.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 2  # kept
    # re-running does not re-stamp already-flagged rows
    assert db.mark_comments_deleted(10, [], "2026-07-11 00:00:00") == 0
    assert db.conn.execute(
        "SELECT deleted_at FROM comments WHERE comment_no=1").fetchone()[0] == _WHEN
    db.close()


def test_mark_posts_deleted_keeps_row(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_post(_post(no=1))
    db.upsert_post(_post(no=2))
    db.upsert_comment(_cmt(post_no=1, comment_no=1))
    db.commit()

    n = db.mark_posts_deleted([1], _WHEN)
    db.commit()
    assert n == 1
    assert db.count_posts_for_date("2026-07-09") == 2       # nothing removed
    r = db.conn.execute("SELECT is_deleted, deleted_at FROM posts WHERE post_no=1").fetchone()
    assert r["is_deleted"] == 1 and r["deleted_at"] == _WHEN
    assert db.conn.execute(
        "SELECT COALESCE(is_deleted,0) FROM posts WHERE post_no=2").fetchone()[0] == 0
    # its comments are kept as-is
    assert db.conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_no=1").fetchone()[0] == 1
    assert db.mark_posts_deleted([], _WHEN) == 0             # no-op on empty
    assert db.mark_posts_deleted([1], "2026-07-11 00:00:00") == 0   # already flagged
    db.close()


def test_upsert_clears_deleted_flag(tmp_path):
    """A post/comment seen alive again must lose its stale 'deleted' mark."""
    db = Database(tmp_path / "t.db")
    db.upsert_post(_post(no=1))
    db.upsert_comment(_cmt(post_no=1, comment_no=1))
    db.mark_posts_deleted([1], _WHEN)
    db.mark_comments_deleted(1, [], _WHEN)
    db.commit()

    db.upsert_post(_post(no=1))                 # re-scraped alive
    db.upsert_comment(_cmt(post_no=1, comment_no=1))
    db.commit()
    p = db.conn.execute("SELECT is_deleted, deleted_at FROM posts WHERE post_no=1").fetchone()
    c = db.conn.execute("SELECT is_deleted, deleted_at FROM comments WHERE post_no=1").fetchone()
    assert p["is_deleted"] == 0 and p["deleted_at"] is None
    assert c["is_deleted"] == 0 and c["deleted_at"] is None
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
