import pytest

from dc_scraper.scraper import _crawl_list, _resolve_range


def test_single_date():
    assert _resolve_range("2026-07-09", None, None) == ("2026-07-09", "2026-07-09")


def test_range_both():
    assert _resolve_range(None, "2026-07-01", "2026-07-08") == ("2026-07-01", "2026-07-08")


def test_range_open_ends():
    # only from -> single day; only to -> single day
    assert _resolve_range(None, "2026-07-01", None) == ("2026-07-01", "2026-07-01")
    assert _resolve_range(None, None, "2026-07-08") == ("2026-07-08", "2026-07-08")


def test_range_inverted_raises():
    with pytest.raises(ValueError):
        _resolve_range(None, "2026-07-08", "2026-07-01")


class _FakeFetcher:
    """Serves canned list pages keyed by page number."""

    def __init__(self, pages: dict[int, str]):
        self.pages = pages
        self.requested: list[int] = []

    def get(self, url: str, referer=None):
        import re
        page = int(re.search(r"page=(\d+)", url).group(1))
        self.requested.append(page)

        class _R:
            text = self.pages.get(page, "")
        return _R()


def _row(no: int, subject: str, ts: str) -> str:
    return (
        f'<tr class="ub-content us-post">'
        f'<td class="gall_num">{no}</td>'
        f'<td class="gall_subject">{subject}</td>'
        f'<td class="gall_tit"><a href="/mgallery/board/view/?id=aichatting&no={no}">t{no}</a></td>'
        f'<td class="gall_writer" data-nick="w"></td>'
        f'<td class="gall_date" title="{ts}">x</td>'
        f'<td class="gall_count">0</td><td class="gall_recommend">0</td></tr>'
    )


def test_crawl_range_filters_and_stops():
    # page1: today (2026-07-09) -> newer than range, skipped, no stop
    # page2: 07-05 and 07-03 -> in range [07-02, 07-05]
    # page3: 07-01 -> older than range -> stop
    pages = {
        1: _row(100, "💬잡담", "2026-07-09 10:00:00") + _row(101, "💬잡담", "2026-07-09 09:00:00"),
        2: _row(90, "💬잡담", "2026-07-05 12:00:00") + _row(91, "공지", "2026-07-05 11:00:00")
           + _row(92, "💬잡담", "2026-07-03 08:00:00"),
        3: _row(80, "💬잡담", "2026-07-01 23:00:00"),
    }
    fake = _FakeFetcher(pages)
    got, complete = _crawl_list(fake, "aichatting", "2026-07-02", "2026-07-05", max_pages=10)
    nos = sorted(p["post_no"] for p in got)
    assert nos == [90, 92]          # 91 is a notice, excluded; today skipped; 07-01 excluded
    assert fake.requested == [1, 2, 3]   # stopped after page 3 (hit older-than-range)
    assert complete is True         # walked past the range's older edge
