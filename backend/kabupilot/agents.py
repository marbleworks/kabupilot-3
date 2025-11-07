"""LLM-powered agent implementations for the CLI backend."""

from __future__ import annotations

import json
import logging
import re
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
from .llm import (
    ChatMessage,
    LLMProviderError,
    OpenAIWithGrokToolProvider,
    SupportsLLMGenerate,
)
from .models import ActivityLog, ExplorerFinding, Goal, ResearchFinding, Transaction
from .repository import PortfolioRepository

LOGGER = logging.getLogger(__name__)

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _extract_json_dict(text: str) -> dict[str, object]:
    """Return the first JSON object contained in ``text``."""

    if not text:
        raise ValueError("Empty response from LLM")

    candidate = text.strip()
    match = _JSON_FENCE_PATTERN.search(candidate)
    if match:
        candidate = match.group(1).strip()

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(candidate[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("LLM response did not contain a JSON object")
    return data


def _format_positions(snapshot) -> str:
    lines: list[str] = []
    for position in snapshot.positions:
        lines.append(
            f"- {position.symbol}: {position.shares:.2f} shares @ ${position.avg_price:,.2f}"
        )
    return "\n".join(lines) if lines else "(none)"


def _format_watchlist(snapshot) -> str:
    lines: list[str] = []
    for entry in snapshot.watchlist:
        lines.append(f"- {entry.symbol}: {entry.note}")
    return "\n".join(lines) if lines else "(none)"


def _record_activity(
    repository: PortfolioRepository,
    *,
    agent: str,
    activity_type: str,
    summary: str,
    details: dict[str, object] | None = None,
) -> None:
    payload = json.dumps(details or {}, ensure_ascii=False, indent=2)
    repository.record_activity(
        ActivityLog(
            timestamp=datetime.utcnow(),
            agent=agent,
            activity_type=activity_type,
            summary=summary,
            details=payload,
        )
    )


class LLMAgentMixin:
    """Utility helpers for agents that rely on an LLM provider."""

    provider: SupportsLLMGenerate

    def _ensure_knowledge(
        self,
        repository: PortfolioRepository,
        *,
        database_path: str | Path | None = None,
    ) -> KnowledgeMemo:
        """Load and cache the shared knowledge memo for a repository."""

        knowledge = self.knowledge  # type: ignore[attr-defined]
        if knowledge is None:
            market = repository.get_market()
            try:
                knowledge = load_knowledge_base(market, database_path=database_path)
            except Exception:  # pragma: no cover - fallback when DB not available
                knowledge = KnowledgeMemo(
                    market=market,
                    content="",
                    updated_at=datetime.utcnow(),
                    editor="unknown",
                )

            self.knowledge = knowledge  # type: ignore[attr-defined]

        return knowledge

    def _call_llm(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        **options: object,
    ) -> str:
        messages = [
            ChatMessage("system", system_prompt.strip()),
            ChatMessage("user", user_prompt.strip()),
        ]
        return self.provider.generate(messages, temperature=temperature, **options)

    def _call_llm_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback: dict[str, object],
        schema_name: str,
        response_schema: dict[str, object],
        temperature: float = 0.2,
        **options: object,
    ) -> tuple[dict[str, object], str | None]:
        try:
            text_options = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": response_schema,
                    "strict": True,
                }
            }
            raw = self._call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                text=text_options,
                **options,
            )
            data = _extract_json_dict(raw)
            return data, raw
        except (LLMProviderError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("LLM request failed (%s); using fallback", exc)
            return fallback, None


@dataclass
class PlannerAgent(LLMAgentMixin):
    repository: PortfolioRepository
    provider: SupportsLLMGenerate
    knowledge: KnowledgeMemo | None = None

    def run(self, week_start: date) -> Goal:
        snapshot = self.repository.portfolio_snapshot()
        knowledge = self._ensure_knowledge(self.repository)

        system_prompt = dedent(
            """
            You are the planning agent for an autonomous portfolio manager.
            Analyse the provided context and propose a concise weekly objective along with
            focus areas, risk checks, and metrics to monitor for the upcoming week.
            """
        )
        user_prompt = dedent(
            f"""
            Week start: {week_start.isoformat()}
            Cash on hand: ${snapshot.cash_balance:,.2f}
            Current positions:\n{_format_positions(snapshot)}
            Watchlist:\n{_format_watchlist(snapshot)}
            Shared memo excerpt:\n{knowledge.content[:2000]}
            """
        )

        fallback = {
            "objective": "Maintain disciplined positioning while sourcing two new high-quality ideas.",
            "focus_areas": [
                "Review existing watchlist for catalysts",
                "Stress test largest holdings versus macro backdrop",
                "Preserve sufficient liquidity for tactical entries",
            ],
            "risk_checks": [
                "Validate position sizing against cash availability",
                "Monitor volatility in benchmark indices",
            ],
            "suggested_metrics": ["net_cash_usage", "new_ideas_identified"],
        }

        plan_schema = {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "risk_checks": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "suggested_metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["objective", "focus_areas", "risk_checks", "suggested_metrics"],
            "additionalProperties": False,
        }

        plan, raw_response = self._call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback=fallback,
            schema_name="PlannerGoal",
            response_schema=plan_schema,
            temperature=0.15,
        )

        content_lines = [
            f"# Weekly Portfolio Goal — {week_start.isoformat()}",
            f"Objective: {plan.get('objective', fallback['objective'])}",
            "",
            "## Focus Areas",
        ]
        for item in plan.get("focus_areas", fallback["focus_areas"]):
            content_lines.append(f"- {item}")
        content_lines.extend(["", "## Risk Checks"])
        for item in plan.get("risk_checks", fallback["risk_checks"]):
            content_lines.append(f"- {item}")
        metrics = plan.get("suggested_metrics", fallback["suggested_metrics"])
        if metrics:
            content_lines.extend(["", "## Suggested Metrics"]) 
            for metric in metrics:
                content_lines.append(f"- {metric}")

        goal = Goal(
            goal_type="weekly",
            period_start=datetime.combine(week_start, datetime.min.time()),
            content="\n".join(content_lines).strip(),
        )
        self.repository.record_goal(goal)

        _record_activity(
            self.repository,
            agent="Planner",
            activity_type="goal",
            summary=plan.get("objective", fallback["objective"]),
            details={"plan": plan, "raw_response": raw_response or ""},
        )

        return goal


@dataclass
class ExplorerAgent(LLMAgentMixin):
    repository: PortfolioRepository
    provider: SupportsLLMGenerate
    knowledge: KnowledgeMemo | None = None
    grok_provider: SupportsLLMGenerate | None = None

    def run(self) -> ExplorerFinding:
        snapshot = self.repository.portfolio_snapshot()
        knowledge = self._ensure_knowledge(self.repository)

        suggested = symbols_from_memo(knowledge)

        fallback = {
            "symbols": (snapshot.watchlist and [entry.symbol for entry in snapshot.watchlist])
            or (suggested or ["SPY", "QQQ"]),
            "rationale": "Rotating through watchlist names and memo highlights to maintain research cadence.",
        }

        explorer_schema = {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "rationale": {"type": "string"},
            },
            "required": ["symbols", "rationale"],
            "additionalProperties": False,
        }

        result = fallback
        raw_response: str | None = None

        if not isinstance(self.grok_provider, OpenAIWithGrokToolProvider):
            raise RuntimeError(
                "ExplorerAgent requires an OpenAIWithGrokToolProvider for Grok-based discovery"
            )

        grok_system_prompt = dedent(
            """
            You are Grok from xAI acting as a market scout scanning X (Twitter).
            Surface trending equities, tickers, or themes investors are actively discussing.
            Focus on concrete chatter that can inspire new research leads.
            """
        ).strip()

        system_prompt = dedent(
            """
            You discover equity symbols to investigate next.
            Always call the grok_search tool to gather fresh X (Twitter) sentiment and trend data
            before finalising your suggestions.
            Propose up to five tickers prioritising diversification and current requests, and
            include a succinct rationale that cites the X insights you gathered.
            """
        )
        user_prompt = dedent(
            f"""
            Cash balance: ${snapshot.cash_balance:,.2f}
            Current positions:\n{_format_positions(snapshot)}
            Watchlist:\n{_format_watchlist(snapshot)}
            Shared memo excerpt:\n{knowledge.content[:2000]}
            Previously suggested symbols from memo: {', '.join(suggested) if suggested else 'none'}
            Highlight how current X trends intersect with this context.
            """
        )

        text_options = {
            "format": {
                "type": "json_schema",
                "name": "ExplorerSuggestion",
                "schema": explorer_schema,
                "strict": True,
            }
        }

        try:
            raw_response = self.grok_provider.generate(
                [
                    ChatMessage("system", system_prompt.strip()),
                    ChatMessage("user", user_prompt.strip()),
                ],
                temperature=0.3,
                grok_system_prompt=grok_system_prompt,
                grok_temperature=0.2,
                text=text_options,
            )
            parsed = json.loads(raw_response)
            if not isinstance(parsed, dict):
                raise ValueError("LLM response did not contain a JSON object")
            result = parsed
        except (LLMProviderError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("Grok-assisted exploration failed; using fallback: %s", exc)

        symbols = [str(symbol).upper() for symbol in result.get("symbols", [])]
        if not symbols:
            symbols = [str(symbol).upper() for symbol in fallback.get("symbols", [])]
        symbols = symbols[:5]

        rationale = str(result.get("rationale") or fallback["rationale"])

        finding = ExplorerFinding(symbols=symbols, rationale=rationale)

        _record_activity(
            self.repository,
            agent="Explorer",
            activity_type="discovery",
            summary=f"Suggested {', '.join(symbols)}",
            details={"result": result, "raw_response": raw_response or ""},
        )

        return finding


@dataclass
class ResearcherAgent(LLMAgentMixin):
    provider: SupportsLLMGenerate
    knowledge: KnowledgeMemo | None = None
    grok_provider: SupportsLLMGenerate | None = None

    def _score_with_grok_tool(self, symbol: str) -> ResearchFinding:
        if not isinstance(self.grok_provider, OpenAIWithGrokToolProvider):
            raise RuntimeError(
                "ResearcherAgent requires an OpenAIWithGrokToolProvider for Grok access"
            )

        knowledge_context = ""
        if self.knowledge:
            context = find_symbol_context(symbol, self.knowledge)
            knowledge_context = context or self.knowledge.content[:1000]

        assert isinstance(self.grok_provider, OpenAIWithGrokToolProvider)

        grok_system_prompt = dedent(
            """
            You are Grok from xAI acting as an external research assistant.
            Return at most five bullet points highlighting timely catalysts, risks, or valuation notes.
            Focus on factual developments that would aid an equity analyst.
            """
        ).strip()

        system_prompt = dedent(
            """
            You are the primary equity analyst for an autonomous portfolio manager.
            When you need fresh market intelligence, call the grok_search tool to consult xAI Grok.
            After reviewing all context, deliver a conviction score between 0 and 1 with a supporting rationale,
            integrating insights from both the shared memo and any Grok findings.
            """
        )
        user_prompt = dedent(
            f"""
            Symbol: {symbol.upper()}
            Shared memo context:\n{knowledge_context or '(no memo excerpts available)'}
            Evaluate the current attractiveness of the name and summarise the thesis.
            """
        )

        fallback_score = 0.55 + (abs(hash(symbol)) % 30) / 100
        fallback = {
            "score": min(1.0, round(fallback_score, 3)),
            "rationale": knowledge_context
            or f"Baseline attractiveness applied for {symbol}; limited contextual insight available.",
        }

        text_options = {
            "format": {
                "type": "json_schema",
                "name": "ResearchScore",
                "schema": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["score", "rationale"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        }

        try:
            raw = self.grok_provider.generate(
                [
                    ChatMessage("system", system_prompt.strip()),
                    ChatMessage("user", user_prompt.strip()),
                ],
                temperature=0.4,
                grok_system_prompt=grok_system_prompt,
                grok_temperature=0.2,
                text=text_options,
            )
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("LLM response did not contain a JSON object")
        except (LLMProviderError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("Tool-enabled research failed for %s: %s", symbol, exc)
            result = fallback

        try:
            score = float(result.get("score", fallback["score"]))
        except (TypeError, ValueError):
            score = float(fallback["score"])
        score = max(0.0, min(1.0, score))

        rationale = str(result.get("rationale") or fallback["rationale"])

        finding = ResearchFinding(symbol=symbol.upper(), score=round(score, 3), rationale=rationale)

        LOGGER.debug("Researcher tool result for %s: %s", symbol, result)

        return finding


@dataclass
class ResearchLeaderAgent:
    researcher: ResearcherAgent

    def run(self, symbols: Iterable[str]) -> Sequence[ResearchFinding]:
        findings = [self.researcher._score_with_grok_tool(symbol) for symbol in symbols]
        return findings


@dataclass
class DeciderAgent(LLMAgentMixin):
    repository: PortfolioRepository
    provider: SupportsLLMGenerate
    knowledge: KnowledgeMemo | None = None

    def run(self, findings: Sequence[ResearchFinding]) -> Sequence[Transaction]:
        if not findings:
            return []

        snapshot = self.repository.portfolio_snapshot()
        knowledge = self._ensure_knowledge(self.repository)

        findings_payload = [
            {"symbol": item.symbol, "score": item.score, "rationale": item.rationale}
            for item in findings
        ]

        system_prompt = dedent(
            """
            You decide trades for the day based on research scores and current holdings.
            Provide a concise summary and recommended trades that respect available cash and
            avoid fractional sells beyond existing holdings.
            """
        )
        user_prompt = dedent(
            f"""
            Cash balance: ${snapshot.cash_balance:,.2f}
            Positions:\n{_format_positions(snapshot)}
            Watchlist:\n{_format_watchlist(snapshot)}
            Research findings (JSON): {json.dumps(findings_payload, ensure_ascii=False)}
            Shared memo excerpt:\n{knowledge.content[:2000]}
            """
        )

        top = max(findings, key=lambda item: item.score)
        fallback_trades: list[dict[str, object]] = []
        price_top = lookup_price(top.symbol)
        max_shares = max(0.0, snapshot.cash_balance // (price_top or 1))
        if max_shares >= 1 and top.score >= 0.6:
            fallback_trades.append(
                {
                    "kind": "buy",
                    "symbol": top.symbol,
                    "shares": float(min(max_shares, 5)),
                    "reason": f"Highest conviction score {top.score:.2f}",
                }
            )

        fallback = {
            "summary": f"Deploy capital into {top.symbol} while trimming sub-threshold holdings if needed.",
            "trades": fallback_trades,
        }

        decider_schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "trades": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["buy", "sell"]},
                            "symbol": {"type": "string"},
                            "shares": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["kind", "symbol", "shares"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "trades"],
            "additionalProperties": False,
        }

        result, raw_response = self._call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback=fallback,
            schema_name="DeciderTrades",
            response_schema=decider_schema,
            temperature=0.2,
        )

        trades: list[Transaction] = []
        available_cash = snapshot.cash_balance
        current_positions = {pos.symbol: pos.shares for pos in snapshot.positions}

        for item in result.get("trades", []):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).lower()
            symbol = str(item.get("symbol", "")).upper()
            if kind not in {"buy", "sell"} or not symbol:
                continue
            try:
                shares = float(item.get("shares", 0.0))
            except (TypeError, ValueError):
                continue
            if shares <= 0:
                continue
            price = lookup_price(symbol)
            if kind == "buy":
                max_affordable = available_cash / price if price > 0 else 0
                if max_affordable <= 0:
                    continue
                shares = min(shares, max(0.0, max_affordable))
                if shares < 1e-6:
                    continue
                available_cash -= shares * price
            else:
                owned = current_positions.get(symbol, 0.0)
                if owned <= 0:
                    continue
                shares = min(shares, owned)
                current_positions[symbol] = owned - shares
            trades.append(
                Transaction(
                    kind=kind,
                    symbol=symbol,
                    shares=round(shares, 4),
                    price=price,
                    reason=str(item.get("reason", result.get("summary", ""))),
                )
            )

        if not trades and fallback_trades:
            for fallback_trade in fallback_trades:
                symbol = str(fallback_trade["symbol"]).upper()
                price = lookup_price(symbol)
                shares = float(fallback_trade.get("shares", 0.0))
                if shares <= 0:
                    continue
                if shares * price > available_cash:
                    continue
                trades.append(
                    Transaction(
                        kind=str(fallback_trade.get("kind", "buy")),
                        symbol=symbol,
                        shares=round(shares, 4),
                        price=price,
                        reason=str(fallback_trade.get("reason", "Fallback action")),
                    )
                )
                break

        if trades:
            summary = result.get("summary") or fallback.get("summary", "Decider trades executed")
        else:
            summary = "No trades executed; constraints prevented action."

        _record_activity(
            self.repository,
            agent="Decider",
            activity_type="decision",
            summary=summary,
            details={"result": result, "raw_response": raw_response or "", "trades": [
                {
                    "kind": trade.kind,
                    "symbol": trade.symbol,
                    "shares": trade.shares,
                    "price": trade.price,
                    "reason": trade.reason,
                }
                for trade in trades
            ]},
        )

        return trades


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
class CheckerAgent(LLMAgentMixin):
    repository: PortfolioRepository
    provider: SupportsLLMGenerate
    knowledge: KnowledgeMemo | None = None
    database_path: str | Path | None = None

    def run(self, as_of: date, *, daily_result: dict | None = None) -> str:
        snapshot = self.repository.portfolio_snapshot()
        knowledge = self.knowledge
        market = self.repository.get_market()
        if knowledge is None:
            knowledge = load_knowledge_base(market, database_path=self.database_path)
        self.knowledge = knowledge

        explorer_symbols: list[str] = []
        research_summary = "No research recorded"
        transaction_summary = "No trades executed"

        if daily_result:
            explorer_data = daily_result.get("explorer")
            if isinstance(explorer_data, dict):
                explorer_symbols = [str(sym).upper() for sym in explorer_data.get("symbols", [])]
            research_items = daily_result.get("research")
            if isinstance(research_items, list) and research_items:
                research_summary = ", ".join(
                    f"{item.get('symbol', '')}:{float(item.get('score', 0)):.2f}"
                    for item in research_items
                    if isinstance(item, dict)
                )
            transactions_items = daily_result.get("transactions")
            if isinstance(transactions_items, list) and transactions_items:
                entries: list[str] = []
                for item in transactions_items:
                    if not isinstance(item, dict):
                        continue
                    entries.append(
                        f"{item.get('kind', '').upper()} {item.get('symbol', '')} {item.get('shares', 0)}"
                    )
                if entries:
                    transaction_summary = "; ".join(entries)

        system_prompt = dedent(
            """
            You are the checker agent summarising the day's activity.
            Use the provided portfolio state and outcomes to craft a daily summary, any
            outstanding requests, memo updates, and a public report suitable for the CLI output.
            """
        )
        user_prompt = dedent(
            f"""
            Date: {as_of.isoformat()}
            Cash balance: ${snapshot.cash_balance:,.2f}
            Positions:\n{_format_positions(snapshot)}
            Watchlist:\n{_format_watchlist(snapshot)}
            Explorer symbols: {', '.join(explorer_symbols) if explorer_symbols else 'none'}
            Research summary: {research_summary}
            Transactions: {transaction_summary}
            Shared memo excerpt:\n{knowledge.content[:2000]}
            """
        )

        fallback_summary = dedent(
            f"""
            Date: {as_of.isoformat()}
            Explorer: {', '.join(explorer_symbols) if explorer_symbols else 'No new symbols'}
            Research: {research_summary}
            Transactions: {transaction_summary}
            Portfolio equity (est.): ${snapshot.total_equity(lambda symbol: lookup_price(symbol)):,.2f}
            Cash balance: ${snapshot.cash_balance:,.2f}
            """
        ).strip()

        fallback = {
            "summary": "Maintain momentum and continue sourcing differentiated ideas.",
            "requests": ["Explorer: identify fresh symbols to evaluate."],
            "history_entry": fallback_summary.replace("\n", " "),
            "memo_update": fallback_summary,
            "public_report": fallback_summary,
        }

        checker_schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "requests": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "history_entry": {"type": "string"},
                "memo_update": {"type": "string"},
                "public_report": {"type": "string"},
            },
            "required": [
                "summary",
                "requests",
                "history_entry",
                "memo_update",
                "public_report",
            ],
            "additionalProperties": False,
        }

        result, raw_response = self._call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback=fallback,
            schema_name="CheckerDailySummary",
            response_schema=checker_schema,
            temperature=0.15,
        )

        memo_summary = str(result.get("memo_update") or fallback["memo_update"])
        requests = [str(item) for item in result.get("requests", fallback["requests"])]
        if not requests:
            requests = fallback["requests"]
        history_entry = str(result.get("history_entry") or fallback["history_entry"])

        update_knowledge_memo(
            market=market,
            database_path=self.database_path,
            transform=lambda current: rewrite_memo_with_daily_digest(
                current,
                latest_summary=memo_summary,
                requests=requests,
                history_entry=history_entry,
                editor="checker",
            ),
        )

        public_report = str(result.get("public_report") or fallback["public_report"])

        _record_activity(
            self.repository,
            agent="Checker",
            activity_type="summary",
            summary=result.get("summary", fallback["summary"]),
            details={"result": result, "raw_response": raw_response or ""},
        )

        return public_report.strip()

