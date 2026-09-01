"""SQLite persistence and upsert helpers for CodePulse."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_PATH.read_text())

    @staticmethod
    def upsert(conn: sqlite3.Connection, table: str, values: dict[str, Any], conflict: str) -> None:
        columns = list(values)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column not in conflict.split(","))
        sql = (f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
               f"ON CONFLICT({conflict}) DO UPDATE SET {assignments}")
        conn.execute(sql, [values[column] for column in columns])

    def upsert_many(self, table: str, records: Iterable[dict[str, Any]], conflict: str) -> int:
        items = list(records)
        if not items:
            return 0
        with self.connect() as conn:
            for record in items:
                self.upsert(conn, table, record, conflict)
        return len(items)
