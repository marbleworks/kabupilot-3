"""Services that provide access to portfolio and capital data."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from ..core.types import CapitalInfo, PortfolioState, Position, WatchItem


@dataclass
class PortfolioRepository:
    """Simple in-memory repository for portfolio information."""

    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    watchlist: Dict[str, WatchItem] = field(default_factory=dict)

    def snapshot(self) -> PortfolioState:
        return PortfolioState(
            cash=self.cash,
            positions=list(self.positions.values()),
            watchlist=list(self.watchlist.values()),
        )

    def update_cash(self, new_cash: float) -> None:
        self.cash = new_cash

    def upsert_position(self, symbol: str, quantity: int, average_price: float) -> None:
        self.positions[symbol] = Position(symbol=symbol, quantity=quantity, average_price=average_price)

    def remove_position(self, symbol: str) -> None:
        self.positions.pop(symbol, None)

    def set_watch_items(self, items: Iterable[WatchItem]) -> None:
        self.watchlist = {item.symbol: item for item in items}

    def add_watch_item(self, symbol: str, rationale: str) -> None:
        self.watchlist[symbol] = WatchItem(symbol=symbol, rationale=rationale)

    def remove_watch_item(self, symbol: str) -> None:
        self.watchlist.pop(symbol, None)


@dataclass
class CapitalService:
    """Service that encapsulates simple capital calculations."""

    portfolio_repository: PortfolioRepository

    def get_capital_info(self) -> CapitalInfo:
        total_equity = self.portfolio_repository.cash
        for position in self.portfolio_repository.positions.values():
            total_equity += position.quantity * position.average_price
        investable_cash = self.portfolio_repository.cash
        return CapitalInfo(total_equity=total_equity, investable_cash=investable_cash)
