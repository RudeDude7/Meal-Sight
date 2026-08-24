"""Shared timestamp parsing for the pantry package.

aiosqlite returns TIMESTAMP columns as plain strings (this project's
Database wrapper doesn't opt into sqlite3's PARSE_DECLTYPES), in the
exact format SQLite's own CURRENT_TIMESTAMP produces: "YYYY-MM-DD
HH:MM:SS", UTC, no timezone suffix.
"""

from __future__ import annotations

from datetime import datetime

_SQLITE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_sqlite_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, _SQLITE_TIMESTAMP_FORMAT)
    except ValueError:
        return datetime.fromisoformat(value)
