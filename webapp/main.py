"""FastAPI application entry point.

Run: ``uvicorn webapp.main:app --reload``
Set ``DC_DB_PATH`` to point at a different SQLite file (default: dcinside.db).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="DCInside 커뮤니티 수집·분석 대시보드", version="0.2.0")
app.include_router(router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
