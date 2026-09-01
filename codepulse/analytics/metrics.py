"""Metric queries and lightweight growth forecasting."""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd


def _frame(conn: sqlite3.Connection, query: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(query, conn, params=params, parse_dates=["period"])


def repositories(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT id, full_name, html_url FROM repositories ORDER BY full_name", conn)


def overview(conn: sqlite3.Connection, repository_id: int) -> dict[str, int]:
    row = conn.execute("""SELECT s.stars, s.forks, s.open_issues,
      (SELECT COUNT(*) FROM contributors c WHERE EXISTS (SELECT 1 FROM commits x WHERE x.repository_id=r.id AND x.contributor_id=c.id)) contributors
      FROM repositories r LEFT JOIN repository_snapshots s ON s.id=(SELECT id FROM repository_snapshots WHERE repository_id=r.id ORDER BY captured_at DESC LIMIT 1)
      WHERE r.id=?""", (repository_id,)).fetchone()
    return dict(row) if row else {"stars": 0, "forks": 0, "open_issues": 0, "contributors": 0}


def contributor_velocity(conn: sqlite3.Connection, repository_id: int, start: date, end: date) -> pd.DataFrame:
    return _frame(conn, """SELECT period, contributor, activity, COUNT(*) AS events FROM (
        SELECT date(c.authored_at, 'weekday 0', '-6 days') AS period, COALESCE(u.login, 'Unknown') AS contributor, 'Commits' AS activity
        FROM commits c LEFT JOIN contributors u ON u.id=c.contributor_id
        WHERE c.repository_id=? AND date(c.authored_at) BETWEEN ? AND ?
        UNION ALL
        SELECT date(p.created_at, 'weekday 0', '-6 days'), COALESCE(u.login, 'Unknown'), 'Pull requests'
        FROM pull_requests p LEFT JOIN contributors u ON u.id=p.author_id
        WHERE p.repository_id=? AND date(p.created_at) BETWEEN ? AND ?
      ) GROUP BY period, contributor, activity ORDER BY period""", (repository_id, str(start), str(end), repository_id, str(start), str(end)))


def issue_resolution(conn: sqlite3.Connection, repository_id: int, start: date, end: date) -> pd.DataFrame:
    return _frame(conn, """SELECT date(closed_at, 'start of month') AS period,
        AVG(julianday(closed_at)-julianday(created_at)) AS resolution_days, COUNT(*) AS closed_issues
        FROM issues WHERE repository_id=? AND closed_at IS NOT NULL AND date(closed_at) BETWEEN ? AND ?
        GROUP BY period ORDER BY period""", (repository_id, str(start), str(end)))


def release_cadence(conn: sqlite3.Connection, repository_id: int, start: date, end: date) -> pd.DataFrame:
    return _frame(conn, """SELECT date(COALESCE(published_at, created_at)) AS period, tag_name,
        julianday(COALESCE(published_at, created_at)) - julianday(LAG(COALESCE(published_at, created_at)) OVER (ORDER BY COALESCE(published_at, created_at))) AS days_since_previous
        FROM releases WHERE repository_id=? AND date(COALESCE(published_at, created_at)) BETWEEN ? AND ?
        ORDER BY period""", (repository_id, str(start), str(end)))


def growth_history(conn: sqlite3.Connection, repository_id: int, start: date, end: date) -> pd.DataFrame:
    return _frame(conn, """SELECT date(captured_at) AS period, MAX(stars) AS stars, MAX(forks) AS forks
        FROM repository_snapshots WHERE repository_id=? AND date(captured_at) BETWEEN ? AND ?
        GROUP BY period ORDER BY period""", (repository_id, str(start), str(end)))
