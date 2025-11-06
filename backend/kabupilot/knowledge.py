"""Utility helpers to work with the static knowledge base."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Iterable, Sequence

MARKET_DATA_FILES: dict[str, str] = {
    "jp": "data/knowledge_base_jp.json",
    "us": "data/knowledge_base_us.json",
}


@dataclass(frozen=True)
class KnowledgeEntry:
    symbol: str
    sector: str
    insight: str
    fair_price: float


def load_knowledge_base(market: str = "jp") -> Sequence[KnowledgeEntry]:
    """Load the static knowledge base for the requested market.

    Parameters
    ----------
    market:
        Either ``"jp"`` (default) for Japanese equities or ``"us"`` for
        U.S. equities.
    """

    normalized = market.lower()
    try:
        resource_name = MARKET_DATA_FILES[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported market '{market}'. Available markets: {', '.join(sorted(MARKET_DATA_FILES))}."
        ) from exc

    with resources.files(__package__).joinpath(resource_name).open("r", encoding="utf-8") as handle:
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
