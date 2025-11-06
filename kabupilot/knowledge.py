"""Utility helpers to work with the static knowledge base."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Iterable, Sequence


@dataclass(frozen=True)
class KnowledgeEntry:
    symbol: str
    sector: str
    insight: str
    fair_price: float


def load_knowledge_base() -> Sequence[KnowledgeEntry]:
    with resources.files(__package__).joinpath("data/knowledge_base.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [
        KnowledgeEntry(
            symbol=str(entry["symbol"]).upper(),
            sector=str(entry["sector"]),
            insight=str(entry["insight"]),
            fair_price=float(entry["fair_price"]),
        )
        for entry in payload
    ]


def lookup_price(symbol: str, knowledge: Iterable[KnowledgeEntry] | None = None) -> float:
    symbol = symbol.upper()
    entries = list(knowledge or load_knowledge_base())
    for entry in entries:
        if entry.symbol == symbol:
            return entry.fair_price
    # Fall back to a synthetic price derived from the ticker so the system can still run.
    return (abs(hash(symbol)) % 40000) / 100 + 20
