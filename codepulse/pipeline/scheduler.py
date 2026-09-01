"""Optional local scheduler for recurring incremental ingestion."""
from __future__ import annotations

import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from db.database import Database
from pipeline.etl import ingest_repository
from pipeline.github_client import GitHubClient


def run() -> None:
    load_dotenv()
    repositories = [r.strip() for r in os.getenv("CODEPULSE_REPOS", "").split(",") if r.strip()]
    if not repositories: raise ValueError("Set CODEPULSE_REPOS before running the scheduler")
    database = Database(os.getenv("CODEPULSE_DB_PATH", "data/codepulse.db"))
    client = GitHubClient(os.getenv("GITHUB_TOKEN"))
    for repo in repositories: print(repo, ingest_repository(repo, database, client))


if __name__ == "__main__":
    load_dotenv()
    scheduler = BlockingScheduler()
    scheduler.add_job(run, "interval", minutes=int(os.getenv("CODEPULSE_POLL_MINUTES", "60")), next_run_time=None)
    run()
    scheduler.start()
