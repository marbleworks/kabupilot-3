"""Simple agent implementations for the CLI backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Sequence

from .knowledge import (
    KnowledgeMemo,
    find_symbol_context,
    load_knowledge_base,
    lookup_price,
    rewrite_memo_with_daily_digest,
    symbols_from_memo,
    update_knowledge_memo,
)
from .models import ExplorerFinding, Goal, ResearchFinding, Transaction
from .repository import PortfolioRepository


@dataclass
class PlannerAgent:
    repository: PortfolioRepository

    def run(self, week_start: date) -> Goal:
        snapshot = self.repository.portfolio_snapshot()
        positions_summary = ", ".join(f"{pos.symbol}:{pos.shares:.1f}" for pos in snapshot.positions) or "no positions"
        cash = snapshot.cash_balance
        focus_sector = "technology" if cash > 50000 else "capital preservation"
        content = dedent(
            f"""
            Focus: {focus_sector} ideas with disciplined risk management.
            Current positions: {positions_summary}
            Cash on hand: ${cash:,.2f}
            Goals: identify at least two attractive opportunities while pruning underperformers.
            """
        ).strip()
        goal = Goal("weekly", datetime.combine(week_start, datetime.min.time()), content)
        self.repository.record_goal(goal)
        return goal


@dataclass
class ExplorerAgent:
    repository: PortfolioRepository
    knowledge: KnowledgeMemo | None = None

    def run(self) -> ExplorerFinding:
        memo = self.knowledge or load_knowledge_base()
        suggested = symbols_from_memo(memo)
        watchlist = self.repository.list_watchlist()
        if not watchlist:
            rationale = "No watchlist entries; using symbols highlighted in the shared memo."
            symbols = suggested[:5]
            if not symbols:
                symbols = ["SPY", "QQQ"]
        else:
            rationale = "Rotating through watchlist names prioritising technology and growth."
            symbols = [entry.symbol for entry in watchlist]
            existing = {symbol for symbol in symbols}
            for symbol in suggested:
                if symbol not in existing:
                    symbols.append(symbol)
                if len(symbols) >= 5:
                    break
        return ExplorerFinding(symbols=symbols, rationale=rationale)


@dataclass
class ResearcherAgent:
    knowledge: KnowledgeMemo | None = None

    def score_symbol(self, symbol: str) -> ResearchFinding:
        memo = self.knowledge or load_knowledge_base()
        context = find_symbol_context(symbol, memo)
        baseline = 0.5 + (abs(hash(symbol)) % 50) / 100
        score = min(1.0, baseline / 1.2)
        if context:
            rationale = context
            score = min(1.0, score + 0.1)
        else:
            rationale = f"No direct insight available for {symbol}."
        return ResearchFinding(symbol=symbol, score=round(score, 3), rationale=rationale)


@dataclass
class ResearchLeaderAgent:
    researcher: ResearcherAgent

    def run(self, symbols: Iterable[str]) -> Sequence[ResearchFinding]:
        return [self.researcher.score_symbol(symbol) for symbol in symbols]


@dataclass
class DeciderAgent:
    repository: PortfolioRepository
    knowledge: KnowledgeMemo | None = None

    def run(self, findings: Sequence[ResearchFinding]) -> Sequence[Transaction]:
        if not findings:
            return []

        scores = sorted(findings, key=lambda finding: finding.score, reverse=True)
        snapshot = self.repository.portfolio_snapshot()
        transactions: list[Transaction] = []
        cash = snapshot.cash_balance
        # Determine sells for low scoring positions.
        low_score_threshold = 0.55
        finding_map = {finding.symbol: finding for finding in findings}
        for position in snapshot.positions:
            finding = finding_map.get(position.symbol)
            if finding and finding.score < low_score_threshold:
                price = lookup_price(position.symbol)
                transactions.append(
                    Transaction(
                        kind="sell",
                        symbol=position.symbol,
                        shares=min(position.shares, 5),
                        price=price,
                        reason=f"Score {finding.score:.2f} below threshold",
                    )
                )

        # Attempt a single buy in the highest scoring name if cash allows.
        top_candidate = scores[0]
        price = lookup_price(top_candidate.symbol)
        lot_size = max(1, int(cash // (price * 2)))
        if lot_size > 0 and top_candidate.score >= 0.6:
            transactions.append(
                Transaction(
                    kind="buy",
                    symbol=top_candidate.symbol,
                    shares=float(lot_size),
                    price=price,
                    reason=f"High conviction score {top_candidate.score:.2f}",
                )
            )
        return transactions


@dataclass
class PortfolioUpdaterAgent:
    explorer: ExplorerAgent
    leader: ResearchLeaderAgent
    decider: DeciderAgent
    repository: PortfolioRepository

    def run(self) -> dict:
        explorer_result = self.explorer.run()
        research_findings = self.leader.run(explorer_result.symbols)
        transactions = self.decider.run(research_findings)
        self.repository.apply_transactions(transactions)
        return {
            "explorer": explorer_result,
            "research": research_findings,
            "transactions": transactions,
        }


@dataclass
class CheckerAgent:
    repository: PortfolioRepository
    knowledge: KnowledgeMemo | None = None
    database_path: str | Path | None = None

    def run(self, as_of: date, *, daily_result: dict | None = None) -> str:
        snapshot = self.repository.portfolio_snapshot()
        total_value = snapshot.total_equity(lambda symbol: lookup_price(symbol))

        explorer_result = None
        research_findings: Sequence[ResearchFinding] = []
        transactions: Sequence[Transaction] = []
        if daily_result:
            explorer_result = daily_result.get("explorer")
            research_findings = daily_result.get("research", [])
            transactions = daily_result.get("transactions", [])

        explorer_summary = (
            ", ".join(explorer_result.symbols)
            if explorer_result and explorer_result.symbols
            else "No symbols proposed"
        )
        research_summary = (
            "; ".join(f"{finding.symbol}:{finding.score:.2f}" for finding in research_findings)
            if research_findings
            else "No research scores recorded"
        )
        transaction_summary = (
            "; ".join(
                f"{tx.kind.upper()} {tx.symbol} {tx.shares:.2f} @ ${tx.price:,.2f}"
                for tx in transactions
            )
            if transactions
            else "No trades executed"
        )

        latest_summary = dedent(
            f"""
            Date: {as_of.isoformat()}
            Explorer: {explorer_summary}
            Research: {research_summary}
            Decider: {transaction_summary}
            Portfolio equity (est.): ${total_value:,.2f}
            Cash balance: ${snapshot.cash_balance:,.2f}
            """
        ).strip()

        requests: list[str] = []
        if explorer_result and not list(explorer_result.symbols):
            requests.append("Explorer: expand symbol discovery to refill the pipeline.")
        if not transactions:
            requests.append("Decider: identify actionable trades to deploy capital.")
        if snapshot.cash_balance > 0 and total_value > 0:
            cash_ratio = snapshot.cash_balance / total_value
            if cash_ratio > 0.4:
                requests.append("Planner: address elevated cash levels above 40% of equity.")
        if not requests:
            requests.append("All agents: continue executing against the weekly objective.")

        history_entry = (
            f"{as_of.isoformat()} — Explorer: {explorer_summary}; "
            f"Research: {research_summary}; Decider: {transaction_summary}; "
            f"Cash ${snapshot.cash_balance:,.2f}"
        )

        market = self.repository.get_market()

        update_knowledge_memo(
            market=market,
            database_path=self.database_path,
            transform=lambda current: rewrite_memo_with_daily_digest(
                current,
                latest_summary=latest_summary,
                requests=requests,
                history_entry=history_entry,
                editor="checker",
            ),
        )

        positions_text = ", ".join(
            f"{pos.symbol} ({pos.shares:.2f} sh)" for pos in snapshot.positions
        ) or "None"

        return dedent(
            f"""
            Date: {as_of.isoformat()}
            Cash: ${snapshot.cash_balance:,.2f}
            Positions: {positions_text}
            Estimated equity value: ${total_value:,.2f}
            Shared memo updated with the latest checker digest.
            """
        ).strip()
