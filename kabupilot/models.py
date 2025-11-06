"""Domain models used by the backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: float
    avg_price: float

    def market_value(self, price: float) -> float:
        return self.shares * price


@dataclass(frozen=True)
class WatchlistEntry:
    symbol: str
    note: str


@dataclass(frozen=True)
class ActivityLog:
    timestamp: datetime
    agent: str
    activity_type: str
    summary: str
    details: str


@dataclass(frozen=True)
class Goal:
    goal_type: str
    period_start: datetime
    content: str


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash_balance: float
    positions: Sequence[Position]
    watchlist: Sequence[WatchlistEntry]

    def total_market_value(self, price_lookup: callable[[str], float]) -> float:
        return sum(position.market_value(price_lookup(position.symbol)) for position in self.positions)

    def total_equity(self, price_lookup: callable[[str], float]) -> float:
        return self.cash_balance + self.total_market_value(price_lookup)


@dataclass(frozen=True)
class Transaction:
    kind: str
    symbol: str
    shares: float
    price: float
    reason: str

    def cash_impact(self) -> float:
        multiplier = -1 if self.kind == "buy" else 1
        return multiplier * self.shares * self.price


@dataclass(frozen=True)
class ResearchFinding:
    symbol: str
    score: float
    rationale: str


@dataclass(frozen=True)
class ExplorerFinding:
    symbols: Iterable[str]
    rationale: str
