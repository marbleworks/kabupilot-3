"""Core domain types for the kabupilot backend."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Sequence


@dataclass
class Position:
    """Represents a single stock position."""

    symbol: str
    quantity: int
    average_price: float

    def to_json(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class WatchItem:
    """Represents an entry in the watch list."""

    symbol: str
    rationale: str = ""

    def to_json(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class PortfolioState:
    """Current snapshot of the portfolio."""

    cash: float
    positions: List[Position] = field(default_factory=list)
    watchlist: List[WatchItem] = field(default_factory=list)

    def find_position(self, symbol: str) -> Optional[Position]:
        for position in self.positions:
            if position.symbol == symbol:
                return position
        return None

    def to_json(self) -> Dict[str, object]:
        return {
            "cash": self.cash,
            "positions": [position.to_json() for position in self.positions],
            "watchlist": [item.to_json() for item in self.watchlist],
        }


@dataclass
class CapitalInfo:
    """Summary of capital that can be deployed."""

    total_equity: float
    investable_cash: float

    def to_json(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class KnowledgeEntry:
    """Single entry stored in the knowledge base."""

    title: str
    content: str
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_json(self) -> Dict[str, object]:
        return {
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ResearchScore:
    """Score assigned to a symbol by research agents."""

    symbol: str
    score: float
    rationale: str

    def to_json(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class Decision:
    """Represents a portfolio change decided by the Decider agent."""

    action: str
    symbol: str
    quantity: int
    price: Optional[float] = None

    def to_json(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class DailyGoal:
    """Goal for a single trading day."""

    text: str
    priority_symbols: Sequence[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, object]:
        return {
            "text": self.text,
            "priority_symbols": list(self.priority_symbols),
        }


@dataclass
class WeeklyGoal:
    """Goal for the week produced by the planner."""

    headline: str
    details: List[str]
    daily_goals: List[DailyGoal]

    def to_json(self) -> Dict[str, object]:
        return {
            "headline": self.headline,
            "details": list(self.details),
            "daily_goals": [goal.to_json() for goal in self.daily_goals],
        }


@dataclass
class AgentSummary:
    """Summary output from any agent."""

    summary: str
    artifacts: Dict[str, object] = field(default_factory=dict)

    def to_json(self) -> Dict[str, object]:
        return {
            "summary": self.summary,
            "artifacts": self.artifacts,
        }


@dataclass
class ActivityRecord:
    """Entry that documents what an agent did and why."""

    agent: str
    action: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_json(self) -> Dict[str, object]:
        payload = {
            "agent": self.agent,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.details is not None:
            payload["details"] = self.details
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


def records_to_json(records: Sequence[ActivityRecord]) -> List[Dict[str, object]]:
    """Utility helper to convert a list of records into JSON serialisable form."""

    return [record.to_json() for record in records]
