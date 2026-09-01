"""Incrementally fetch GitHub data and load normalized records into SQLite."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from db.database import Database
from pipeline.github_client import GitHubClient, utc_now


def user_record(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user or user.get("id") is None:
        return None
    return {"id": user["id"], "login": user.get("login", "ghost"), "avatar_url": user.get("avatar_url"), "html_url": user.get("html_url")}


def latest_sync(conn, repository_id: int) -> str | None:
    row = conn.execute("SELECT max(fetched_at) AS value FROM repositories WHERE id = ?", (repository_id,)).fetchone()
    if not row or not row["value"]:
        return None
    # overlap avoids missing changes made close to the prior request
    return (datetime.fromisoformat(row["value"]).replace(tzinfo=timezone.utc) - timedelta(minutes=5)).isoformat()


def ingest_repository(full_name: str, database: Database, client: GitHubClient) -> dict[str, int]:
    database.initialize()
    repository = client.repository(full_name)
    fetched_at = utc_now()
    repo_record = {key: repository.get(key) for key in ("id", "full_name", "description", "html_url", "default_branch", "created_at", "updated_at")}
    repo_record.update({"owner": repository["owner"]["login"], "name": repository["name"], "fetched_at": fetched_at})
    counts = {"commits": 0, "issues": 0, "pull_requests": 0, "releases": 0, "contributors": 0}
    with database.connect() as conn:
        since = latest_sync(conn, repository["id"])
        Database.upsert(conn, "repositories", repo_record, "id")
        for item in client.contributors(full_name):
            record = user_record(item)
            if record:
                Database.upsert(conn, "contributors", record, "id"); counts["contributors"] += 1
        for item in client.commits(full_name, since):
            author = user_record(item.get("author"))
            if author: Database.upsert(conn, "contributors", author, "id")
            commit = item.get("commit", {})
            Database.upsert(conn, "commits", {"sha": item["sha"], "repository_id": repository["id"], "contributor_id": author["id"] if author else None, "authored_at": commit.get("author", {}).get("date"), "message": commit.get("message"), "url": item.get("html_url")}, "sha")
            counts["commits"] += 1
        for item in client.issues(full_name, since):
            if "pull_request" in item: continue
            author = user_record(item.get("user"))
            if author: Database.upsert(conn, "contributors", author, "id")
            Database.upsert(conn, "issues", {"id": item["id"], "repository_id": repository["id"], "author_id": author["id"] if author else None, "number": item["number"], "title": item["title"], "state": item["state"], "created_at": item["created_at"], "closed_at": item.get("closed_at"), "updated_at": item.get("updated_at"), "comments": item.get("comments", 0), "html_url": item.get("html_url")}, "id")
            counts["issues"] += 1
        for item in client.pull_requests(full_name, since):
            author = user_record(item.get("user"))
            if author: Database.upsert(conn, "contributors", author, "id")
            Database.upsert(conn, "pull_requests", {"id": item["id"], "repository_id": repository["id"], "author_id": author["id"] if author else None, "number": item["number"], "title": item["title"], "state": item["state"], "created_at": item["created_at"], "closed_at": item.get("closed_at"), "merged_at": item.get("merged_at"), "updated_at": item.get("updated_at"), "additions": item.get("additions"), "deletions": item.get("deletions"), "changed_files": item.get("changed_files"), "html_url": item.get("html_url")}, "id")
            counts["pull_requests"] += 1
        for item in client.releases(full_name):
            Database.upsert(conn, "releases", {"id": item["id"], "repository_id": repository["id"], "tag_name": item["tag_name"], "name": item.get("name"), "published_at": item.get("published_at"), "created_at": item["created_at"], "prerelease": int(item.get("prerelease", False)), "html_url": item.get("html_url")}, "id")
            counts["releases"] += 1
        conn.execute("INSERT OR IGNORE INTO repository_snapshots (repository_id, captured_at, stars, forks, open_issues) VALUES (?, ?, ?, ?, ?)", (repository["id"], fetched_at, repository["stargazers_count"], repository["forks_count"], repository["open_issues_count"]))
    return counts


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ingest GitHub repository activity into CodePulse.")
    parser.add_argument("repos", nargs="*", help="owner/repository values; defaults to CODEPULSE_REPOS")
    parser.add_argument("--db", default=os.getenv("CODEPULSE_DB_PATH", "data/codepulse.db"))
    args = parser.parse_args()
    repositories = args.repos or [value.strip() for value in os.getenv("CODEPULSE_REPOS", "").split(",") if value.strip()]
    if not repositories: parser.error("Provide repos or set CODEPULSE_REPOS")
    client, database = GitHubClient(os.getenv("GITHUB_TOKEN")), Database(args.db)
    for repo in repositories:
        print(f"{repo}: {ingest_repository(repo, database, client)}")


if __name__ == "__main__": main()
