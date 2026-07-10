"""Configuration constants for the DCInside scraper.

Selectors and endpoint parameters are centralized here so that a site markup
change only requires edits in one place.
"""

from __future__ import annotations

# --- Target gallery ---------------------------------------------------------
DEFAULT_GALLERY_ID = "aichatting"

# mgallery (minor gallery) vs regular gallery. Affects URL path and _GALLTYPE_.
GALLERY_KIND = "mgallery"       # "mgallery" | "board"
GALLTYPE = "M"                  # "M" for minor gallery, "" for regular

BASE = "https://gall.dcinside.com"

# --- HTTP -------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Random delay (seconds) applied between requests to be polite / avoid blocks.
DELAY_MIN = 1.0
DELAY_MAX = 2.5

# Retry / backoff
MAX_RETRIES = 3
BACKOFF_BASE = 2.0          # seconds; exponential: BASE * 2**attempt
BLOCK_COOLDOWN = 60.0       # long wait when a 403/429 block is detected
REQUEST_TIMEOUT = 20.0

# Safety cap so a broken end-condition never crawls forever.
DEFAULT_MAX_PAGES = 100

# --- List page selectors ----------------------------------------------------
ROW_SELECTOR = "tr.ub-content.us-post"
SEL_NUM = ".gall_num"
SEL_SUBJECT = ".gall_subject"       # 말머리 (category). "공지" => notice, skip.
SEL_TITLE = ".gall_tit a"
SEL_WRITER = ".gall_writer"
SEL_DATE = ".gall_date"             # full timestamp in `title` attribute
SEL_COUNT = ".gall_count"
SEL_RECOMMEND = ".gall_recommend"

# Subject (말머리) values that mark non-article rows to be excluded.
NOTICE_SUBJECTS = {"공지", "설문", "AD", "광고"}

# --- View page selectors ----------------------------------------------------
SEL_BODY = ".gallview_contents .write_div, .write_div"
SEL_ESNO = 'input[name="e_s_n_o"]'
SEL_VIEW_TITLE = ".title_subject"
SEL_VIEW_COUNT = ".gall_count"       # "조회 123"
SEL_VIEW_RECOMMEND = ".up_num"       # 추천 count on view page
SEL_VIEW_DISLIKE = ".down_num"       # 비추천 count on view page

# --- Comment AJAX -----------------------------------------------------------
COMMENT_ENDPOINT = f"{BASE}/board/comment/"
