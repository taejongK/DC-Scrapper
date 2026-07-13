"""Background scrape-job manager.

Scraping is long-running, so the API starts it in a daemon thread and the client
polls status. We keep a small in-memory registry plus the durable record the
scraper itself writes to the ``scrape_runs`` table.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, asdict

from dc_scraper.fetch import Fetcher
from dc_scraper.scraper import collect


@dataclass
class Job:
    id: str
    params: dict
    status: str = "running"          # running | success | partial | failed
    summary: dict | None = None
    error: str | None = None


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def _run(self, job: Job) -> None:
        try:
            fetcher = Fetcher(
                delay_min=job.params.get("delay_min", 1.0),
                delay_max=job.params.get("delay_max", 2.5),
            )
            summary = collect(
                gallery_id=job.params["gallery_id"],
                target_date=job.params.get("target_date"),
                date_from=job.params.get("date_from"),
                date_to=job.params.get("date_to"),
                db_path=job.params["db_path"],
                fetcher=fetcher,
                max_pages=job.params.get("max_pages", 100),
                with_comments=job.params.get("with_comments", True),
            )
            with self._lock:
                job.summary = summary
                job.status = summary["status"]
        except Exception as exc:  # noqa: BLE001 - surface any failure to the client
            with self._lock:
                job.status = "failed"
                job.error = str(exc)

    def start(self, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], params=params)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self) -> Job | None:
        with self._lock:
            return next(reversed(self._jobs.values()), None) if self._jobs else None

    def all(self) -> list[dict]:
        with self._lock:
            return [asdict(j) for j in self._jobs.values()]


manager = JobManager()
