from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def list_html() -> str:
    return (FIX / "list_page.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def view_html() -> str:
    return (FIX / "view_page.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def comments_json() -> str:
    return (FIX / "comments.json").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def adult_html() -> str:
    return (FIX / "adult_page.html").read_text(encoding="utf-8", errors="replace")
