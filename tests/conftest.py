"""Shared fixture: a small temp SQLite DB for analysis/webapp tests."""

from pathlib import Path

import pytest

from dc_scraper.db import Database

_POSTS = [
    # post_no, title, writer, posted_at, views, rec, cmt, category, body, adult
    (1, "에덴 신드롬 진짜 좋다", "ㅇㅇ", "2026-07-08 09:00:00", 100, 10, 2, "💬잡담", "이 캐릭터 정말 좋아 최고야", 0),
    (2, "젬 별로임 짜증나", "abc", "2026-07-08 22:30:00", 50, 1, 1, "📕리뷰", "출력이 느리고 답답해 최악", 0),
    (3, "NSFW 지침 공유", "ㅇㅇ", "2026-07-09 01:15:00", 200, 20, 0, "📜정보", "", 1),
    (4, "질문 있어요", "def", "2026-07-09 14:00:00", 30, 0, 1, "❓질문", "이거 어떻게 설정하나요", 0),
]
_COMMENTS = [
    # post_no, comment_no, parent, writer, content, posted_at, is_reply
    (1, 11, None, "ㅇㅇ", "나도 좋아 완전 추천", "07.08 09:05:00", 0),
    (1, 12, 11, "kk", "재밌다 진짜", "07.08 09:10:00", 1),
    (2, 21, None, "ㅇㅇ", "맞아 짜증나고 별로야", "07.08 22:40:00", 0),
    (4, 41, None, "zz", "그냥 그렇다", "07.09 14:05:00", 0),
]


@pytest.fixture
def sample_db(tmp_path) -> str:
    path = str(tmp_path / "sample.db")
    db = Database(path)
    for (no, title, writer, posted, v, r, cc, cat, body, adult) in _POSTS:
        db.upsert_post({
            "post_no": no, "gallery_id": "aichatting", "title": title, "writer": writer,
            "posted_at": posted, "view_count": v, "recommend": r, "dislike": 0,
            "comment_cnt": cc, "category": cat, "body_text": body, "body_html": f"<p>{body}</p>",
            "is_adult": adult, "url": f"http://x/{no}", "scraped_at": "2026-07-09 15:00:00",
        })
    for (pno, cno, parent, writer, content, posted, reply) in _COMMENTS:
        db.upsert_comment({
            "post_no": pno, "comment_no": cno, "parent_no": parent, "writer": writer,
            "writer_ip": "1.2", "content": content, "posted_at": posted,
            "is_reply": reply, "scraped_at": "2026-07-09 15:00:00",
        })
    db.commit()
    db.close()
    return path
