"""In-memory knowledge base implementation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from ..core.types import KnowledgeEntry


@dataclass
class KnowledgeBase:
    """A small in-memory knowledge base that can be updated by agents."""

    entries: List[KnowledgeEntry] = field(default_factory=list)

    def add_entry(self, entry: KnowledgeEntry) -> None:
        self.entries.append(entry)

    def search(self, keyword: str) -> List[KnowledgeEntry]:
        keyword_lower = keyword.lower()
        return [entry for entry in self.entries if keyword_lower in entry.content.lower() or keyword_lower in entry.title.lower()]

    def latest(self, limit: Optional[int] = None) -> List[KnowledgeEntry]:
        data = sorted(self.entries, key=lambda e: e.created_at, reverse=True)
        if limit is not None:
            data = data[:limit]
        return data

    def to_json(self) -> List[Dict[str, object]]:
        return [entry.to_json() for entry in self.entries]

    def extend(self, entries: Iterable[KnowledgeEntry]) -> None:
        for entry in entries:
            self.add_entry(entry)
