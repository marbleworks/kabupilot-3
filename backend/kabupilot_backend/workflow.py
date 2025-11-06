"""High level orchestration for the kabupilot backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .agents.checker import Checker
from .agents.dicider import Dicider
from .agents.planner import Planner
from .agents.portfolio_updater import PortfolioUpdater
from .agents.explorer import Explorer
from .agents.research_leader import ResearchLeader
from .core.types import DailyGoal, WeeklyGoal, KnowledgeEntry
from .services.data_providers import CapitalService, PortfolioRepository
from .tools.external import GrokTool, InternetSearchTool
from .tools.knowledge_base import KnowledgeBase


@dataclass
class PortfolioAutomationSystem:
    """Bundles all agents and exposes methods to drive the workflow."""

    knowledge_base: KnowledgeBase = field(default_factory=KnowledgeBase)
    portfolio_repository: PortfolioRepository = field(default_factory=lambda: PortfolioRepository(cash=10000.0))
    internet_search: InternetSearchTool = field(default_factory=InternetSearchTool)
    grok_tool: GrokTool = field(default_factory=GrokTool)

    def __post_init__(self) -> None:
        self.capital_service = CapitalService(self.portfolio_repository)
        self.planner = Planner(
            name="Planner",
            knowledge_base=self.knowledge_base,
            capital_service=self.capital_service,
            portfolio_repository=self.portfolio_repository,
        )
        if not self.knowledge_base.entries:
            self.knowledge_base.extend(
                [
                    KnowledgeEntry(title="AAPL", content="Strong cash flow and services growth."),
                    KnowledgeEntry(title="MSFT", content="Cloud adoption momentum continues."),
                    KnowledgeEntry(title="TSLA", content="Volatility warrants cautious sizing."),
                ]
            )
        explorer = Explorer(name="Explorer", knowledge_base=self.knowledge_base, search_tool=self.internet_search)
        research_leader = ResearchLeader(
            name="ResearchLeader",
            knowledge_base=self.knowledge_base,
            search_tool=self.internet_search,
            grok_tool=self.grok_tool,
        )
        dicider = Dicider(
            name="Dicider",
            knowledge_base=self.knowledge_base,
            capital_service=self.capital_service,
        )
        self.portfolio_updater = PortfolioUpdater(
            name="PortfolioUpdater",
            explorer=explorer,
            research_leader=research_leader,
            dicider=dicider,
            portfolio_repository=self.portfolio_repository,
        )
        self.checker = Checker(
            name="Checker",
            knowledge_base=self.knowledge_base,
            capital_service=self.capital_service,
            portfolio_repository=self.portfolio_repository,
        )

    def plan_week(self) -> Dict[str, object]:
        return self.planner.run()

    def run_trading_day(self, daily_goal_payload: Dict[str, object]) -> Dict[str, object]:
        daily_goal = DailyGoal(text=daily_goal_payload["text"], priority_symbols=daily_goal_payload.get("priority_symbols", []))
        return self.portfolio_updater.run(daily_goal)

    def review_day(self, activity_log: List[Dict[str, object]], weekly_goal_payload: Dict[str, object]) -> Dict[str, object]:
        weekly_goal = WeeklyGoal(
            headline=weekly_goal_payload["headline"],
            details=list(weekly_goal_payload.get("details", [])),
            daily_goals=[
                DailyGoal(text=goal["text"], priority_symbols=goal.get("priority_symbols", []))
                for goal in weekly_goal_payload.get("daily_goals", [])
            ],
        )
        return self.checker.run(activity_log, weekly_goal)
