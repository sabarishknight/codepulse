# CodePulse

CodePulse is a Streamlit dashboard that turns GitHub REST API data into practical open-source health metrics: contribution velocity, issue resolution time, release cadence, and a simple 30-day star-growth forecast.

## Architecture

```text
GitHub REST API → pipeline/GitHubClient → pipeline/ETL → SQLite
                                                    ↓
                              analytics/metrics + forecasting → Streamlit dashboard
```

The ETL process uses paginated GitHub API requests, waits for rate-limit resets, performs idempotent upserts, and overlaps the previous sync by five minutes to capture late updates. Repository snapshots are recorded on each ingestion, enabling growth trends from that point forward.

## Setup

```bash
cd codepulse
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `GITHUB_TOKEN` in `.env` to a GitHub fine-grained personal access token with read access to the repositories you want to analyse. Public repositories can be fetched without a token, but rate limits are substantially lower.

## Run

Fetch one or more repositories, then start the dashboard:

```bash
python -m pipeline.etl psf/requests pallets/flask
streamlit run dashboard/app.py
```

For recurring incremental ingestion, set `CODEPULSE_REPOS=psf/requests,pallets/flask` and run:

```bash
python -m pipeline.scheduler
```

Alternatively schedule `python -m pipeline.etl` through cron. Use `CODEPULSE_DB_PATH` to place the SQLite database elsewhere.

## Data model

The SQLite schema includes `repositories`, `contributors`, `commits`, `issues`, `pull_requests`, and `releases`, plus `repository_snapshots` for historical stars, forks, and open issue counts. SQL views cover weekly commit/PR contributor velocity and issue resolution durations. See `db/schema.sql` for the full schema and indexes.

## Forecasting

The dashboard applies a transparent least-squares linear trend to captured daily star counts. It intentionally requires two snapshots before displaying a projection; this keeps the prediction honest when a project has only just been added.
