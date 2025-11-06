"""Checker agent evaluates progress and updates the knowledge base."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, KnowledgeEntry, WeeklyGoal
from ..services.data_providers import CapitalService, PortfolioRepository
from ..tools.knowledge_base import KnowledgeBase


@dataclass
class Checker(BaseAgent):
    knowledge_base: KnowledgeBase
    capital_service: CapitalService
    portfolio_repository: PortfolioRepository

    def run(self, activity_log: List[Dict[str, object]], weekly_goal: WeeklyGoal) -> Dict[str, object]:
        self.reset_activity()
        portfolio = self.portfolio_repository.snapshot()
        capital = self.capital_service.get_capital_info()
        self.log("portfolio", details="Snapshot for evaluation", metadata=portfolio.to_json())
        self.log("capital", details="Capital check", metadata=capital.to_json())

        trade_actions = [item for item in activity_log if item.get("action") in {"buy", "sell"}]
        insights = [
            f"Executed {len(trade_actions)} trade-related activities during the session.",
            f"Current cash position: {portfolio.cash:.2f}.",
        ]
        if portfolio.cash < capital.total_equity * 0.1:
            insights.append("Cash buffer below 10%; consider trimming positions.")
        else:
            insights.append("Cash buffer healthy relative to total equity.")

        kb_entry = KnowledgeEntry(
            title=f"Post-mortem {datetime.utcnow().date().isoformat()}",
            content="\n".join(insights + ["Weekly focus: " + weekly_goal.headline]),
        )
        self.knowledge_base.add_entry(kb_entry)
        self.log("knowledge-base", details="Recorded evaluation entry", metadata={"title": kb_entry.title})

        summary = AgentSummary(
            summary="Daily review completed and knowledge base updated.",
            artifacts={
                "insights": insights,
                "knowledge_entry": kb_entry.to_json(),
            },
        )
        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
        }
