"""High level data access helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .db import get_connection
from .models import ActivityLog, Goal, Position, PortfolioSnapshot, Transaction, WatchlistEntry


class PortfolioRepository:
    """Encapsulates persistence logic for the portfolio domain."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self._database_path = database_path

    # ------------------------------------------------------------------
    # Settings management
    # ------------------------------------------------------------------
    def _ensure_settings_table(self) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def get_setting(self, key: str, *, default: str | None = None) -> str | None:
        self._ensure_settings_table()
        with get_connection(self._database_path) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                if default is None:
                    return None
                connection.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (key, default),
                )
                connection.commit()
                return default
            return str(row[0])

    def set_setting(self, key: str, value: str) -> None:
        self._ensure_settings_table()
        with get_connection(self._database_path) as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            connection.commit()

    def get_market(self) -> str:
        value = self.get_setting("market", default="jp")
        assert value is not None
        return value

    def set_market(self, market: str) -> None:
        if market not in {"jp", "us"}:
            raise ValueError("Unsupported market; expected 'jp' or 'us'")
        self.set_setting("market", market)

    # ------------------------------------------------------------------
    # Portfolio primitives
    # ------------------------------------------------------------------
    def get_cash_balance(self) -> float:
        with get_connection(self._database_path) as connection:
            (row,) = connection.execute("SELECT cash_balance FROM portfolio_meta WHERE id = 1").fetchall()
            return float(row[0])

    def update_cash_balance(self, new_balance: float) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute(
                "UPDATE portfolio_meta SET cash_balance = ? WHERE id = 1",
                (float(new_balance),),
            )
            connection.commit()

    def list_positions(self) -> Sequence[Position]:
        with get_connection(self._database_path) as connection:
            rows = connection.execute(
                "SELECT symbol, shares, avg_price FROM positions ORDER BY symbol"
            ).fetchall()
            return [Position(str(row[0]), float(row[1]), float(row[2])) for row in rows]

    def upsert_position(self, position: Position) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO positions (symbol, shares, avg_price) VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET shares = excluded.shares, avg_price = excluded.avg_price
                """,
                (position.symbol, float(position.shares), float(position.avg_price)),
            )
            connection.commit()

    def remove_position(self, symbol: str) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            connection.commit()

    def list_watchlist(self) -> Sequence[WatchlistEntry]:
        with get_connection(self._database_path) as connection:
            rows = connection.execute("SELECT symbol, note FROM watchlist ORDER BY symbol").fetchall()
            return [WatchlistEntry(str(row[0]), str(row[1])) for row in rows]

    def replace_watchlist(self, entries: Iterable[WatchlistEntry]) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute("DELETE FROM watchlist")
            connection.executemany(
                "INSERT INTO watchlist (symbol, note) VALUES (?, ?)",
                [(entry.symbol, entry.note) for entry in entries],
            )
            connection.commit()

    def record_activity(self, activity: ActivityLog) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO activity_log (timestamp, agent, activity_type, summary, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    activity.timestamp.isoformat(),
                    activity.agent,
                    activity.activity_type,
                    activity.summary,
                    activity.details,
                ),
            )
            connection.commit()

    def list_activity(self, limit: int = 50) -> Sequence[ActivityLog]:
        with get_connection(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT timestamp, agent, activity_type, summary, details
                FROM activity_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                ActivityLog(
                    datetime.fromisoformat(str(row[0])),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                )
                for row in rows
            ]

    def record_goal(self, goal: Goal) -> None:
        with get_connection(self._database_path) as connection:
            connection.execute(
                "INSERT INTO goals (goal_type, period_start, content) VALUES (?, ?, ?)",
                (goal.goal_type, goal.period_start.isoformat(), goal.content),
            )
            connection.commit()

    def latest_goal(self, goal_type: str) -> Goal | None:
        with get_connection(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT goal_type, period_start, content
                FROM goals
                WHERE goal_type = ?
                ORDER BY period_start DESC, id DESC
                LIMIT 1
                """,
                (goal_type,),
            ).fetchone()
            if row is None:
                return None
            return Goal(str(row[0]), datetime.fromisoformat(str(row[1])), str(row[2]))

    def portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            cash_balance=self.get_cash_balance(),
            positions=self.list_positions(),
            watchlist=self.list_watchlist(),
        )

    def apply_transactions(self, transactions: Sequence[Transaction]) -> None:
        if not transactions:
            return

        with get_connection(self._database_path) as connection:
            cursor = connection.cursor()
            (cash_row,) = cursor.execute(
                "SELECT cash_balance FROM portfolio_meta WHERE id = 1"
            ).fetchall()
            cash_balance = float(cash_row[0])

            for tx in transactions:
                if tx.kind not in {"buy", "sell"}:
                    raise ValueError(f"Unsupported transaction type: {tx.kind}")

                cash_balance += tx.cash_impact()
                if cash_balance < 0:
                    raise ValueError("Transaction set would cause negative cash balance")

                position_row = cursor.execute(
                    "SELECT shares, avg_price FROM positions WHERE symbol = ?",
                    (tx.symbol,),
                ).fetchone()

                if tx.kind == "buy":
                    new_shares = (position_row[0] if position_row else 0.0) + tx.shares
                    if position_row:
                        prev_total = position_row[0] * position_row[1]
                        new_total = prev_total + tx.shares * tx.price
                        new_avg = new_total / new_shares
                    else:
                        new_avg = tx.price
                    cursor.execute(
                        """
                        INSERT INTO positions (symbol, shares, avg_price) VALUES (?, ?, ?)
                        ON CONFLICT(symbol) DO UPDATE SET shares = excluded.shares, avg_price = excluded.avg_price
                        """,
                        (tx.symbol, new_shares, new_avg),
                    )
                else:  # sell
                    if position_row is None:
                        raise ValueError(f"Cannot sell {tx.symbol}; no existing position")
                    remaining_shares = position_row[0] - tx.shares
                    if remaining_shares < -1e-6:
                        raise ValueError(f"Cannot sell more shares than owned for {tx.symbol}")
                    if remaining_shares <= 1e-6:
                        cursor.execute("DELETE FROM positions WHERE symbol = ?", (tx.symbol,))
                    else:
                        cursor.execute(
                            "UPDATE positions SET shares = ? WHERE symbol = ?",
                            (remaining_shares, tx.symbol),
                        )

                cursor.execute(
                    "INSERT INTO activity_log (timestamp, agent, activity_type, summary, details) VALUES (?, ?, ?, ?, ?)",
                    (
                        datetime.utcnow().isoformat(),
                        "Decider",
                        f"transaction:{tx.kind}",
                        f"{tx.kind.upper()} {tx.symbol}",
                        json.dumps(asdict(tx)),
                    ),
                )

            cursor.execute(
                "UPDATE portfolio_meta SET cash_balance = ? WHERE id = 1",
                (cash_balance,),
            )
            connection.commit()
