"""HTTP session wrapper: browser-like headers, polite delay, retry/backoff."""

from __future__ import annotations

import logging
import random
import time

import requests

from . import config

log = logging.getLogger(__name__)


class BlockedError(RuntimeError):
    """Raised when the server appears to be blocking us (403/429)."""


class Fetcher:
    """A thin wrapper around requests.Session with rate limiting and retries.

    A single Fetcher instance keeps cookies across requests, which DCInside
    needs (the comment AJAX call relies on cookies set by the view page).
    """

    def __init__(
        self,
        *,
        delay_min: float = config.DELAY_MIN,
        delay_max: float = config.DELAY_MAX,
        max_retries: int = config.MAX_RETRIES,
        rng: random.Random | None = None,
    ) -> None:
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_retries = max_retries
        self._rng = rng or random.Random()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _sleep(self) -> None:
        time.sleep(self._rng.uniform(self.delay_min, self.delay_max))

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._sleep()
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:  # network-level failure
                last_exc = exc
                log.warning("request error (%s), attempt %d: %s", url, attempt + 1, exc)
                time.sleep(config.BACKOFF_BASE * (2 ** attempt))
                continue

            if resp.status_code in (403, 429):
                log.warning("blocked %s on %s; cooling down", resp.status_code, url)
                time.sleep(config.BLOCK_COOLDOWN)
                last_exc = BlockedError(f"{resp.status_code} for {url}")
                continue
            if resp.status_code >= 500:
                log.warning("server %s on %s, attempt %d", resp.status_code, url, attempt + 1)
                time.sleep(config.BACKOFF_BASE * (2 ** attempt))
                last_exc = requests.HTTPError(f"{resp.status_code} for {url}")
                continue

            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp

        assert last_exc is not None
        raise last_exc

    def get(self, url: str, *, referer: str | None = None) -> requests.Response:
        headers = {"Referer": referer} if referer else {}
        return self._request("GET", url, headers=headers)

    def post(self, url: str, data: dict, *, referer: str | None = None,
             ajax: bool = True) -> requests.Response:
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        return self._request("POST", url, data=data, headers=headers)
