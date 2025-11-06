"""External integrations are stubbed for the prototype implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class InternetSearchTool:
    """Simulates internet search results for a symbol."""

    def search_symbol(self, symbol: str) -> List[str]:
        return [
            f"News headline about {symbol}",
            f"Analyst commentary on {symbol}",
            f"Social sentiment summary for {symbol}",
        ]


@dataclass
class GrokTool:
    """Stub that mimics access to social network chatter."""

    def check_symbol(self, symbol: str) -> str:
        return f"Trending discussions for {symbol} indicate neutral sentiment."
