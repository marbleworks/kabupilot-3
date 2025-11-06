"""Utility helpers to work with the SQLite-backed knowledge base."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .db import get_connection


@dataclass(frozen=True)
class KnowledgeEntry:
    market: str
    symbol: str
    sector: str
    insight: str
    fair_price: float
    source: str
    recorded_at: datetime


DEFAULT_KNOWLEDGE_SEEDS: Mapping[str, Sequence[Mapping[str, object]]] = {
    "jp": (
        {
            "symbol": "7203.T",
            "sector": "automotive",
            "insight": (
                "Explorer feedback: Toyota retains wide dealer coverage in Japan; focus on EV"
                " launch readiness during weekly planning."
            ),
            "fair_price": 2250.0,
            "source": "seed:research-2024w10",
        },
        {
            "symbol": "6758.T",
            "sector": "electronics",
            "insight": (
                "Research retrospective noted that Sony's sensor exports cushioned FX swings."
                " Track progress when assigning researcher follow-ups."
            ),
            "fair_price": 13500.0,
            "source": "seed:research-2024w10",
        },
        {
            "symbol": "8306.T",
            "sector": "financials",
            "insight": (
                "Post-trade analysis highlighted Mitsubishi UFJ as low-volatility cash park."
                " Use when cash exceeds 40% of equity."
            ),
            "fair_price": 1200.0,
            "source": "seed:portfolio-review",
        },
        {
            "symbol": "8035.T",
            "sector": "semiconductors",
            "insight": (
                "Daily checker flagged Tokyo Electron supply-chain resilience; keep in the"
                " short list for technology rotations."
            ),
            "fair_price": 23000.0,
            "source": "seed:checker-summary",
        },
        {
            "symbol": "2914.T",
            "sector": "consumer staples",
            "insight": (
                "Activity log review: Calbee price momentum softened but volume steady."
                " Consider trimming only after confirming two weak weekly scans."
            ),
            "fair_price": 3200.0,
            "source": "seed:activity-review",
        },
    ),
    "us": (
        {
            "symbol": "AAPL",
            "sector": "technology",
            "insight": (
                "Research synthesis shows Apple services margin expansion offsets hardware"
                " cyclicality; bias to accumulate on pullbacks."
            ),
            "fair_price": 195.0,
            "source": "seed:research-2024q1",
        },
        {
            "symbol": "MSFT",
            "sector": "technology",
            "insight": (
                "Cross-agent retrospective: Azure AI growth improves recurring revenue"
                " visibility; allocate when cash above $30k."
            ),
            "fair_price": 340.0,
            "source": "seed:planning-retro",
        },
        {
            "symbol": "TSLA",
            "sector": "automotive",
            "insight": (
                "Decider post-mortem suggests pairing Tesla entries with tighter position"
                " sizing due to delivery volatility."
            ),
            "fair_price": 210.0,
            "source": "seed:transaction-review",
        },
        {
            "symbol": "NVDA",
            "sector": "semiconductors",
            "insight": (
                "Checker summaries emphasise Nvidia backlog strength; prioritise for"
                " growth-oriented rebalancing weeks."
            ),
            "fair_price": 620.0,
            "source": "seed:checker-summary",
        },
        {
            "symbol": "JNJ",
            "sector": "healthcare",
            "insight": (
                "Exploration notes: Johnson & Johnson dividend stability useful for"
                " offsetting tech concentration risk."
            ),
            "fair_price": 165.0,
            "source": "seed:explorer-journal",
        },
    ),
}


def _ensure_table(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            sector TEXT NOT NULL,
            insight TEXT NOT NULL,
            fair_price REAL NOT NULL,
            source TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_market_symbol
            ON knowledge_entries (market, symbol);
        """
    )


def ensure_seed_knowledge(*, database_path: str | Path | None = None) -> None:
    """Populate the knowledge base with default collaborative insights if empty."""

    with get_connection(database_path) as connection:
        _ensure_table(connection)
        (existing_count,) = connection.execute(
            "SELECT COUNT(1) FROM knowledge_entries"
        ).fetchone()
        if existing_count:
            return

        payload: list[tuple[str, str, str, str, float, str, str]] = []
        timestamp = datetime.utcnow().isoformat()
        for market, entries in DEFAULT_KNOWLEDGE_SEEDS.items():
            for entry in entries:
                payload.append(
                    (
                        market,
                        str(entry["symbol"]).upper(),
                        str(entry["sector"]),
                        str(entry["insight"]),
                        float(entry["fair_price"]),
                        str(entry["source"]),
                        timestamp,
                    )
                )

        connection.executemany(
            """
            INSERT INTO knowledge_entries (
                market,
                symbol,
                sector,
                insight,
                fair_price,
                source,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        connection.commit()


def load_knowledge_base(
    market: str | None = "jp",
    *,
    database_path: str | Path | None = None,
) -> Sequence[KnowledgeEntry]:
    """Load the knowledge base for the requested market from SQLite."""

    params: list[object] = []
    query = (
        "SELECT market, symbol, sector, insight, fair_price, source, recorded_at"
        " FROM knowledge_entries"
    )
    if market:
        query += " WHERE market = ?"
        params.append(market.lower())
    query += " ORDER BY recorded_at DESC, id DESC"

    with get_connection(database_path) as connection:
        _ensure_table(connection)
        rows = connection.execute(query, params).fetchall()

    return [
        KnowledgeEntry(
            market=str(row["market"]),
            symbol=str(row["symbol"]).upper(),
            sector=str(row["sector"]),
            insight=str(row["insight"]),
            fair_price=float(row["fair_price"]),
            source=str(row["source"]),
            recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
        )
        for row in rows
    ]


def record_knowledge_entry(
    *,
    market: str,
    symbol: str,
    sector: str,
    insight: str,
    fair_price: float,
    source: str,
    database_path: str | Path | None = None,
    recorded_at: datetime | None = None,
) -> None:
    """Persist a new knowledge entry so other agents can reuse the insight."""

    with get_connection(database_path) as connection:
        _ensure_table(connection)
        connection.execute(
            """
            INSERT INTO knowledge_entries (
                market,
                symbol,
                sector,
                insight,
                fair_price,
                source,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market.lower(),
                symbol.upper(),
                sector,
                insight,
                float(fair_price),
                source,
                (recorded_at or datetime.utcnow()).isoformat(),
            ),
        )
        connection.commit()


def lookup_price(symbol: str, knowledge: Iterable[KnowledgeEntry] | None = None) -> float:
    """Return the stored fair price for ``symbol`` or a deterministic fallback."""

    symbol = symbol.upper()
    entries = list(knowledge or load_knowledge_base())
    for entry in entries:
        if entry.symbol == symbol:
            return entry.fair_price
    # Fall back to a synthetic price derived from the ticker so the system can still run.
    return (abs(hash(symbol)) % 40000) / 100 + 20
