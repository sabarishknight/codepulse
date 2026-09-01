"""Session-scoped GitHub Search discovery utilities for the Streamlit app."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests


LANGUAGES = (
    ("Python", "#4f8cff"), ("JavaScript", "#f7c948"), ("TypeScript", "#37c8dc"),
    ("Rust", "#ff875f"), ("Go", "#68d9c1"), ("Java", "#ff7aad"),
)
TOPICS = (
    ("machine-learning", "#d878ef"), ("cli", "#76cef7"), ("web-framework", "#f7c948"),
    ("game-engine", "#69d88e"), ("developer-tools", "#ff937a"), ("data-visualization", "#a894ff"),
)
CACHE_SECONDS = 240


@dataclass(frozen=True)
class Bucket:
    name: str
    color: str


class SearchPacer:
    """Shares a safe request schedule across the small worker pool."""
    def __init__(self, token_present: bool) -> None:
        self.interval = 2.1 if token_present else 6.1  # 30/min token, 10/min unauthenticated
        self.next_at = 0.0
        self.lock = threading.Lock()

    def wait_turn(self) -> None:
        with self.lock:
            wait = max(0.0, self.next_at - time.monotonic())
            self.next_at = max(self.next_at, time.monotonic()) + self.interval
        if wait:
            time.sleep(wait)


def bucket_set(view: str) -> list[Bucket]:
    source = LANGUAGES if view == "Language" else TOPICS
    return [Bucket(*entry) for entry in source]


def _range(days: int, previous: bool) -> tuple[str, str]:
    end = date.today() - timedelta(days=days if previous else 0)
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def _search(bucket: Bucket, view: str, days: int, previous: bool, token: str, pacer: SearchPacer) -> dict[str, Any]:
    start, end = _range(days, previous)
    qualifier = f"language:{bucket.name}" if view == "Language" else f"topic:{bucket.name}"
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"q": f"is:public {qualifier} created:{start}..{end}", "sort": "stars", "order": "desc", "per_page": 8}
    for attempt in range(4):
        pacer.wait_turn()
        response = requests.get("https://api.github.com/search/repositories", params=params, headers=headers, timeout=30)
        if response.status_code not in (403, 429):
            response.raise_for_status()
            return response.json()
        reset = int(response.headers.get("X-RateLimit-Reset", "0") or 0)
        retry_after = float(response.headers.get("Retry-After", "0") or 0)
        backoff = max(retry_after, (reset - time.time() + 1) if reset else 0, 1.5 * (2 ** attempt))
        if attempt == 3:
            raise RuntimeError("GitHub is rate limiting this scan. Please wait a minute and try again.")
        time.sleep(min(backoff, 60))
    raise RuntimeError("GitHub search did not complete.")


def load_pulse(view: str, days: int, token: str, cache: dict[str, tuple[float, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Load current and previous windows, reusing only fresh session-memory results."""
    buckets = bucket_set(view)
    pacer = SearchPacer(bool(token))

    def one(bucket: Bucket) -> dict[str, Any]:
        output: dict[str, Any] = {"bucket": bucket}
        for previous, label in ((False, "current"), (True, "previous")):
            cache_key = f"{view}:{days}:{previous}:{bucket.name}"
            cached = cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
                output[label] = cached[1]
            else:
                value = _search(bucket, view, days, previous, token, pacer)
                cache[cache_key] = (time.monotonic(), value)
                output[label] = value
        return output

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(one, bucket) for bucket in buckets]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item["current"]["total_count"], reverse=True)
