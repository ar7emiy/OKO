"""Polite HTTP fetching: honest UA, throttle, retries, atomic downloads.

Politeness rules are engine-enforced (docs/data-sourcing-engine.md §3.2):
identify ourselves, rate-limit per host, back off on 429/503, never evade.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from oko_ingest import __version__

USER_AGENT = f"OKO-ingest/{__version__} (+mailto:data@oko.example)"

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


class PoliteFetcher:
    """Throttled, retrying downloader for bulk files and small API calls."""

    def __init__(
        self,
        min_interval_s: float = 1.0,
        timeout_s: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._last_request: dict[str, float] = {}
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
            follow_redirects=True,
        )

    def _throttle(self, url: str) -> None:
        host = httpx.URL(url).host or ""
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_request[host] = time.monotonic()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self._throttle(url)
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp

    def download(self, url: str, dest: str | Path, params: dict | None = None) -> Path:
        """Stream a (possibly large) file to disk atomically."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        self._throttle(url)
        with self._client.stream("GET", url, params=params) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
        tmp.replace(dest)
        return dest

    def close(self) -> None:
        self._client.close()
