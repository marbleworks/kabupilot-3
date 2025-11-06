"""Explorer agent implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, PortfolioState
from ..tools.external import InternetSearchTool
from ..tools.knowledge_base import KnowledgeBase


@dataclass
class Explorer(BaseAgent):
    knowledge_base: KnowledgeBase
    search_tool: InternetSearchTool

    def run(self, portfolio: PortfolioState) -> Dict[str, object]:
        self.reset_activity()
        candidates: List[str] = []

        for entry in self.knowledge_base.latest(limit=5):
            self.log("knowledge-base", details=f"Referenced KB entry: {entry.title}")
            if entry.title not in candidates:
                candidates.append(entry.title)

        self.log("portfolio-scan", details="Scanning existing watchlist")
        for watch in portfolio.watchlist:
            if watch.symbol not in candidates:
                candidates.append(watch.symbol)

        self.log("internet-search", details="Running lightweight symbol discovery")
        for position in portfolio.positions:
            for headline in self.search_tool.search_symbol(position.symbol):
                if position.symbol not in candidates:
                    candidates.append(position.symbol)
                self.log("search-result", details=headline, metadata={"symbol": position.symbol})

        summary = AgentSummary(
            summary=f"Identified {len(candidates)} candidate symbols for deeper research.",
            artifacts={"candidates": candidates},
        )
        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
        }
