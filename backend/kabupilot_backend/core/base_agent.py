"""Common utilities shared across agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .types import ActivityRecord, records_to_json


@dataclass
class BaseAgent:
    """Simple base class that handles logging and JSON conversion."""

    name: str
    activity: List[ActivityRecord] = field(default_factory=list, init=False)

    def log(self, action: str, *, details: str | None = None, metadata: Dict[str, object] | None = None) -> None:
        record = ActivityRecord(agent=self.name, action=action, details=details, metadata=metadata or {})
        self.activity.append(record)

    def reset_activity(self) -> None:
        self.activity.clear()

    def activity_json(self) -> List[Dict[str, object]]:
        return records_to_json(self.activity)
