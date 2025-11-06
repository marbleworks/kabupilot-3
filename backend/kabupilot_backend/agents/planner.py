"""Planner agent responsible for setting weekly goals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, DailyGoal, PortfolioState, WeeklyGoal
from ..services.data_providers import CapitalService, PortfolioRepository
from ..tools.knowledge_base import KnowledgeBase


TRADING_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


@dataclass
class Planner(BaseAgent):
    knowledge_base: KnowledgeBase
    capital_service: CapitalService
    portfolio_repository: PortfolioRepository

    def run(self) -> Dict[str, object]:
        self.reset_activity()
        portfolio = self.portfolio_repository.snapshot()
        capital = self.capital_service.get_capital_info()

        self.log("portfolio-snapshot", metadata=portfolio.to_json(), details="Fetched current portfolio state")
        self.log("capital", metadata=capital.to_json(), details="Calculated available capital")

        top_positions = sorted(portfolio.positions, key=lambda pos: pos.quantity * pos.average_price, reverse=True)[:3]
        focus_symbols = [position.symbol for position in top_positions]
        knowledge_highlights = [entry.title for entry in self.knowledge_base.latest(limit=3)]

        details: List[str] = [
            f"Maintain cash buffer above 15% (currently {capital.investable_cash / max(capital.total_equity, 1):.0%}).",
        ]
        if focus_symbols:
            details.append(f"Monitor key holdings: {', '.join(focus_symbols)}.")
        if knowledge_highlights:
            details.append(f"Incorporate insights from KB: {', '.join(knowledge_highlights)}.")

        daily_goals = [
            DailyGoal(
                text=f"{day}: refresh research pipeline and validate alignment with weekly goal.",
                priority_symbols=focus_symbols,
            )
            for day in TRADING_DAYS
        ]

        weekly_goal = WeeklyGoal(
            headline="Improve portfolio resilience while sourcing new opportunities.",
            details=details,
            daily_goals=daily_goals,
        )
        summary = AgentSummary(
            summary="Weekly goal defined and distributed across trading days.",
            artifacts={"weekly_goal": weekly_goal.to_json()},
        )
        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
        }
