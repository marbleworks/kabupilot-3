"""Utility helpers to work with the SQLite-backed knowledge memo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .db import get_connection


@dataclass(frozen=True)
class KnowledgeMemo:
    """Represents the shared memo that all agents can read."""

    market: str
    content: str
    updated_at: datetime
    editor: str


DEFAULT_SYMBOL_NOTES = {
    "jp": (
        "- 7203.T — Core mobility benchmark for EV roll-out progress.",
        "- 6758.T — Imaging growth leverages global demand.",
        "- 8035.T — Semiconductor capital expenditure gauge.",
        "- 9432.T — Defensive telecom cash generator.",
        "- 2914.T — Consumer staples ballast for volatility.",
    ),
    "us": (
        "- AAPL — Platform ecosystem with services tailwinds.",
        "- MSFT — Cloud and AI enterprise exposure.",
        "- NVDA — GPU leadership amid AI investment cycle.",
        "- TSLA — EV innovation with position sizing discipline.",
        "- JNJ — Healthcare stabiliser for portfolio balance.",
    ),
}

DEFAULT_MEMO_TEMPLATE = """# Shared Agent Memo ({market_label})

## Purpose
- Maintain a single memo where agents can review recent activity summaries, lessons,
  and requests before starting their next task.

## Latest Daily Summary
_No daily runs have been recorded yet._

## Open Requests
- Awaiting the first checker summary to derive concrete requests.

## Historical Notes
- Memo created to replace the per-symbol knowledge base.
{symbol_lines}
"""


def _default_content_for_market(market: str) -> str:
    market_key = market.lower()
    market_label = "JP" if market_key == "jp" else "US"
    symbol_lines = "\n" + "\n".join(DEFAULT_SYMBOL_NOTES.get(market_key, ()))
    return DEFAULT_MEMO_TEMPLATE.format(market_label=market_label, symbol_lines=symbol_lines)


def _ensure_table(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            market TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            editor TEXT NOT NULL
        );
        """
    )


def ensure_seed_knowledge(*, database_path: str | Path | None = None) -> None:
    """Ensure that the shared memo exists for both supported markets."""

    with get_connection(database_path) as connection:
        _ensure_table(connection)
        timestamp = datetime.utcnow().isoformat()
        for market in ("jp", "us"):
            connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_documents (market, content, updated_at, editor)
                VALUES (?, ?, ?, ?)
                """,
                (market, _default_content_for_market(market), timestamp, "system"),
            )
        connection.commit()


def load_knowledge_base(
    market: str | None = "jp",
    *,
    database_path: str | Path | None = None,
) -> KnowledgeMemo:
    """Load the shared memo for the requested market from SQLite."""

    resolved_market = (market or "jp").lower()
    with get_connection(database_path) as connection:
        _ensure_table(connection)
        row = connection.execute(
            "SELECT market, content, updated_at, editor FROM knowledge_documents WHERE market = ?",
            (resolved_market,),
        ).fetchone()
        if row is None:
            ensure_seed_knowledge(database_path=database_path)
            row = connection.execute(
                "SELECT market, content, updated_at, editor FROM knowledge_documents WHERE market = ?",
                (resolved_market,),
            ).fetchone()
        assert row is not None
        return KnowledgeMemo(
            market=str(row["market"]),
            content=str(row["content"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            editor=str(row["editor"]),
        )


def update_knowledge_memo(
    *,
    market: str,
    transform: Callable[[KnowledgeMemo], KnowledgeMemo],
    database_path: str | Path | None = None,
) -> KnowledgeMemo:
    """Apply ``transform`` to the stored memo and persist the new version."""

    current = load_knowledge_base(market, database_path=database_path)
    updated = transform(current)
    with get_connection(database_path) as connection:
        _ensure_table(connection)
        connection.execute(
            """
            UPDATE knowledge_documents
            SET content = ?, updated_at = ?, editor = ?
            WHERE market = ?
            """,
            (updated.content, updated.updated_at.isoformat(), updated.editor, market.lower()),
        )
        connection.commit()
    return updated


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,5}(?:\.[A-Z]{1,2})?$")


def symbols_from_memo(memo: KnowledgeMemo, *, limit: int = 5) -> list[str]:
    """Extract symbol mentions from bullet lists in the memo."""

    symbols: list[str] = []
    for line in memo.content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        remainder = stripped[1:].strip()
        if not remainder:
            continue
        token = remainder.split(maxsplit=1)[0].rstrip("—:-")
        if not SYMBOL_PATTERN.match(token):
            continue
        symbol = token.upper()
        if symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return symbols


def find_symbol_context(symbol: str, memo: KnowledgeMemo) -> str | None:
    """Return the memo line mentioning ``symbol`` if present."""

    upper = symbol.upper()
    fallback: str | None = None
    for line in memo.content.splitlines():
        if upper not in line.upper():
            continue
        stripped = line.strip()
        if stripped.startswith("-"):
            remainder = stripped[1:].strip()
            token = remainder.split(maxsplit=1)[0].rstrip("—:-") if remainder else ""
            if SYMBOL_PATTERN.match(token or "") and token.upper() == upper:
                return remainder
        if fallback is None:
            fallback = stripped
    return fallback


def _parse_sections(content: str) -> tuple[str, dict[str, str]]:
    header_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    buffer: list[str] = []

    lines = content.splitlines()
    for line in lines:
        if line.startswith("## "):
            if current_section is None:
                header_lines = buffer
            else:
                sections[current_section] = buffer
            current_section = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)

    if current_section is None:
        header_lines = buffer
    else:
        sections[current_section] = buffer

    normalized_sections = {
        key: "\n".join(value).strip()
        for key, value in sections.items()
    }
    header = "\n".join(header_lines).strip()
    return header, normalized_sections


def _render_sections(header: str, sections: dict[str, str]) -> str:
    ordered_titles = [
        "Purpose",
        "Latest Daily Summary",
        "Open Requests",
        "Historical Notes",
    ]
    parts: list[str] = []
    if header:
        parts.append(header.strip())

    for title in ordered_titles:
        body = sections.get(title)
        if body is None:
            continue
        parts.append(f"## {title}\n{body.strip() if body else ''}".rstrip())

    # Include any additional sections that may have been added over time.
    for title, body in sections.items():
        if title in ordered_titles:
            continue
        parts.append(f"## {title}\n{body.strip() if body else ''}".rstrip())

    return "\n\n".join(filter(None, parts))


def rewrite_memo_with_daily_digest(
    memo: KnowledgeMemo,
    *,
    latest_summary: str,
    requests: Sequence[str],
    history_entry: str,
    editor: str,
) -> KnowledgeMemo:
    """Produce a new memo incorporating the checker digest."""

    header, sections = _parse_sections(memo.content)

    summary_body = latest_summary.strip() or "_No summary recorded._"
    sections["Latest Daily Summary"] = summary_body

    request_lines = [f"- {item}" for item in requests if item]
    if not request_lines:
        request_lines = ["- No outstanding requests; maintain discipline."]
    sections["Open Requests"] = "\n".join(request_lines)

    history_block = sections.get("Historical Notes", "")
    history_lines = [line.strip() for line in history_block.splitlines() if line.strip()]
    history_lines.insert(0, history_entry.strip())
    # Keep the history from growing unbounded while still giving context.
    history_lines = history_lines[:20]
    sections["Historical Notes"] = "\n".join(f"- {line.lstrip('- ').strip()}" for line in history_lines)

    new_content = _render_sections(header, sections)
    return KnowledgeMemo(
        market=memo.market,
        content=new_content,
        updated_at=datetime.utcnow(),
        editor=editor,
    )


def lookup_price(symbol: str, knowledge: Iterable[object] | None = None) -> float:
    """Return a deterministic synthetic price for ``symbol``.

    The memo no longer stores per-symbol fair values, so we fall back to a stable hash-based
    price that keeps the simulator functional while agents rely on the shared memo for
    qualitative coordination.
    """

    symbol = symbol.upper()
    return (abs(hash(symbol)) % 40000) / 100 + 20
