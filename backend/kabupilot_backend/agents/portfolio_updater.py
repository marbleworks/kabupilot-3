"""PortfolioUpdater coordinates daily operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, DailyGoal, Decision, ResearchScore
from ..services.data_providers import PortfolioRepository
from .dicider import Dicider
from .explorer import Explorer
from .research_leader import ResearchLeader


@dataclass
class PortfolioUpdater(BaseAgent):
    explorer: Explorer
    research_leader: ResearchLeader
    dicider: Dicider
    portfolio_repository: PortfolioRepository

    def run(self, daily_goal: DailyGoal) -> Dict[str, object]:
        self.reset_activity()
        portfolio = self.portfolio_repository.snapshot()
        self.log("daily-goal", details=daily_goal.text, metadata={"priority_symbols": list(daily_goal.priority_symbols)})

        explorer_output = self.explorer.run(portfolio)
        candidates = explorer_output["summary"]["artifacts"]["candidates"]
        self.log("explorer", details="Received explorer candidates", metadata={"count": len(candidates)})

        research_output = self.research_leader.run(candidates)
        research_scores_payload = research_output["summary"]["artifacts"]["scores"]
        scores = [
            ResearchScore(symbol=item["symbol"], score=item["score"], rationale=item["rationale"])
            for item in research_scores_payload
        ]
        self.log("research-leader", details="Collected research scores", metadata={"count": len(scores)})

        decisions_output = self.dicider.run(scores, portfolio)
        decision_payloads = decisions_output["summary"]["artifacts"]["decisions"]
        decisions = [
            Decision(action=item["action"], symbol=item["symbol"], quantity=item["quantity"], price=item.get("price"))
            for item in decision_payloads
        ]
        self.log("dicider", details="Dicider returned trade instructions", metadata={"count": len(decisions)})

        self._apply_decisions(decisions)
        summary = AgentSummary(
            summary="Daily portfolio update completed.",
            artifacts={
                "decisions": [decision.to_json() for decision in decisions],
                "explorer_activity": explorer_output["activity"],
                "research_activity": research_output["activity"],
                "dicider_activity": decisions_output["activity"],
            },
        )
        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
        }

    def _apply_decisions(self, decisions: List[Decision]) -> None:
        for decision in decisions:
            if decision.action == "buy":
                self._apply_buy(decision)
            elif decision.action == "sell":
                self._apply_sell(decision)
            elif decision.action == "watch-add":
                self.portfolio_repository.add_watch_item(decision.symbol, decision.quantity)
            self.log(
                decision.action,
                details=f"Executed {decision.action} for {decision.symbol}",
                metadata={"quantity": decision.quantity, "price": decision.price},
            )

    def _apply_buy(self, decision: Decision) -> None:
        price = decision.price or 0.0
        cost = decision.quantity * price
        portfolio = self.portfolio_repository
        portfolio.update_cash(max(0.0, portfolio.cash - cost))
        existing = portfolio.positions.get(decision.symbol)
        if existing:
            total_quantity = existing.quantity + decision.quantity
            if total_quantity > 0:
                new_avg_price = (
                    existing.average_price * existing.quantity + price * decision.quantity
                ) / total_quantity
            else:
                new_avg_price = price
            portfolio.upsert_position(decision.symbol, total_quantity, new_avg_price)
        else:
            portfolio.upsert_position(decision.symbol, decision.quantity, price)

    def _apply_sell(self, decision: Decision) -> None:
        price = decision.price or 0.0
        proceeds = decision.quantity * price
        portfolio = self.portfolio_repository
        portfolio.update_cash(portfolio.cash + proceeds)
        existing = portfolio.positions.get(decision.symbol)
        if existing:
            remaining = existing.quantity - decision.quantity
            if remaining > 0:
                portfolio.upsert_position(decision.symbol, remaining, existing.average_price)
            else:
                portfolio.remove_position(decision.symbol)
