"""Low-level database helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import get_database_path

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS portfolio_meta (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        cash_balance REAL NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL UNIQUE,
        shares REAL NOT NULL,
        avg_price REAL NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL UNIQUE,
        note TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        agent TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        goal_type TEXT NOT NULL,
        period_start TEXT NOT NULL,
        content TEXT NOT NULL
    );
    """
)


@contextmanager
def get_connection(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with sensible defaults."""

    database_path = get_database_path(path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(path: str | Path | None = None, *, force: bool = False) -> Path:
    """Create the database schema if it does not yet exist.

    Parameters
    ----------
    path:
        Optional override for the database path. When ``None`` the default path
        determined by :func:`get_database_path` is used.
    force:
        When ``True`` the database file is removed if it already exists.
    """

    database_path = get_database_path(path)
    if force and database_path.exists():
        database_path.unlink()

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(database_path) as connection:
        cursor = connection.cursor()
        for statement in SCHEMA_STATEMENTS:
            cursor.executescript(statement)
        cursor.execute(
            "INSERT OR IGNORE INTO portfolio_meta (id, cash_balance) VALUES (1, ?)",
            (100000.0,),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("market", "jp"),
        )
        connection.commit()
    return database_path
