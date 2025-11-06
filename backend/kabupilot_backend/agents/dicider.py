"""Dicider agent responsible for proposing portfolio changes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, Decision, PortfolioState, ResearchScore
from ..services.data_providers import CapitalService
from ..tools.knowledge_base import KnowledgeBase


@dataclass
class Dicider(BaseAgent):
    knowledge_base: KnowledgeBase
    capital_service: CapitalService

    def run(self, scores: List[ResearchScore], portfolio: PortfolioState) -> Dict[str, object]:
        self.reset_activity()
        self.log("knowledge-base", details="Reviewing knowledge for context")
        kb_entries = self.knowledge_base.latest(limit=2)
        for entry in kb_entries:
            self.log("kb-entry", details=entry.title)

        capital = self.capital_service.get_capital_info()
        self.log("capital", details="Fetched capital info", metadata=capital.to_json())

        scores_sorted = sorted(scores, key=lambda item: item.score, reverse=True)
        buy_candidates = [score for score in scores_sorted if score.score >= 0.6]
        sell_candidates = [score for score in scores_sorted if score.score <= 0.4 and portfolio.find_position(score.symbol)]

        decisions: List[Decision] = []
        allocation = 0.0
        if buy_candidates:
            allocation = capital.investable_cash / len(buy_candidates)
        for candidate in buy_candidates:
            quantity = int(allocation // 100)  # assume 100 currency units per share for prototype
            if quantity > 0:
                decisions.append(Decision(action="buy", symbol=candidate.symbol, quantity=quantity, price=100.0))
                self.log("decision", details=f"Buy {candidate.symbol}", metadata={"quantity": quantity})

        for candidate in sell_candidates:
            position = portfolio.find_position(candidate.symbol)
            if position and position.quantity > 0:
                sell_quantity = max(1, position.quantity // 2)
                decisions.append(Decision(action="sell", symbol=candidate.symbol, quantity=sell_quantity, price=position.average_price))
                self.log("decision", details=f"Sell {candidate.symbol}", metadata={"quantity": sell_quantity})

        updated_watch = [decision.symbol for decision in decisions if decision.action == "buy"]
        summary = AgentSummary(
            summary=f"Generated {len(decisions)} trade decisions.",
            artifacts={
                "decisions": [decision.to_json() for decision in decisions],
                "watch_additions": updated_watch,
            },
        )
        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
        }
