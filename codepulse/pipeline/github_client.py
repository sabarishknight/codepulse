"""Small GitHub REST API client with pagination and rate-limit awareness."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterator

import requests


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        while True:
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
                reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
                time.sleep(max(1, reset - int(time.time()) + 1))
                continue
            response.raise_for_status()
            return response

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request(f"{self.BASE_URL}{path}", params).json()

    def paginate(self, path: str, **params: Any) -> Iterator[dict[str, Any]]:
        url = f"{self.BASE_URL}{path}"
        query = {"per_page": 100, **params}
        while url:
            response = self._request(url, query)
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError(f"Expected a list from {url}")
            yield from payload
            url = response.links.get("next", {}).get("url")
            query = None

    def repository(self, full_name: str) -> dict[str, Any]:
        return self.get(f"/repos/{full_name}")

    def commits(self, full_name: str, since: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/repos/{full_name}/commits", since=since) if since else self.paginate(f"/repos/{full_name}/commits")

    def issues(self, full_name: str, since: str | None = None) -> Iterator[dict[str, Any]]:
        args = {"state": "all", "since": since} if since else {"state": "all"}
        return self.paginate(f"/repos/{full_name}/issues", **args)

    def pull_requests(self, full_name: str, since: str | None = None) -> Iterator[dict[str, Any]]:
        # GitHub's pull endpoint has no `since` parameter. It is newest-first, so
        # stop as soon as the incremental boundary is reached.
        for item in self.paginate(f"/repos/{full_name}/pulls", state="all", sort="updated", direction="desc"):
            updated = item.get("updated_at")
            if since and updated and _parse_time(updated) < _parse_time(since):
                break
            yield item

    def releases(self, full_name: str) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/repos/{full_name}/releases")

    def contributors(self, full_name: str) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/repos/{full_name}/contributors")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
