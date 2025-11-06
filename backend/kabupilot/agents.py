"""Simple agent implementations for the CLI backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from textwrap import dedent
from typing import Iterable, Sequence

from .knowledge import KnowledgeEntry, load_knowledge_base, lookup_price
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
    knowledge: Sequence[KnowledgeEntry] | None = None

    def run(self) -> ExplorerFinding:
        knowledge = list(self.knowledge or load_knowledge_base())
        watchlist = self.repository.list_watchlist()
        if not watchlist:
            rationale = "No watchlist entries; falling back to knowledge base sectors."
            symbols = [entry.symbol for entry in knowledge[:5]]
        else:
            rationale = "Rotating through watchlist names prioritising technology and growth."
            symbols = [entry.symbol for entry in watchlist]
            existing = {symbol for symbol in symbols}
            for entry in knowledge:
                if entry.symbol not in existing:
                    symbols.append(entry.symbol)
                if len(symbols) >= 5:
                    break
        return ExplorerFinding(symbols=symbols, rationale=rationale)


@dataclass
class ResearcherAgent:
    knowledge: Sequence[KnowledgeEntry] | None = None

    def score_symbol(self, symbol: str) -> ResearchFinding:
        knowledge = list(self.knowledge or load_knowledge_base())
        entry = next((item for item in knowledge if item.symbol == symbol), None)
        baseline = 0.5 + (abs(hash(symbol)) % 50) / 100
        score = min(1.0, baseline / 1.2)
        if entry:
            rationale = entry.insight
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
    knowledge: Sequence[KnowledgeEntry] | None = None

    def run(self, findings: Sequence[ResearchFinding]) -> Sequence[Transaction]:
        if not findings:
            return []

        knowledge = list(self.knowledge or load_knowledge_base())
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
                price = lookup_price(position.symbol, knowledge)
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
        price = lookup_price(top_candidate.symbol, knowledge)
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
    knowledge: Sequence[KnowledgeEntry] | None = None

    def run(self, as_of: date) -> str:
        snapshot = self.repository.portfolio_snapshot()
        knowledge = list(self.knowledge or load_knowledge_base())
        total_value = snapshot.total_equity(lambda symbol: lookup_price(symbol, knowledge))
        return dedent(
            f"""
            Date: {as_of.isoformat()}
            Cash: ${snapshot.cash_balance:,.2f}
            Positions: {', '.join(f"{pos.symbol} ({pos.shares:.2f} sh)" for pos in snapshot.positions) or 'None'}
            Estimated equity value: ${total_value:,.2f}
            """
        ).strip()
