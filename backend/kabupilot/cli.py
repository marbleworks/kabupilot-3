"""Command line interface for the kabupilot backend."""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence

from .agents import (
    CheckerAgent,
    DeciderAgent,
    ExplorerAgent,
    PlannerAgent,
    PortfolioUpdaterAgent,
    ResearchLeaderAgent,
    ResearcherAgent,
)
from .config import get_database_path
from .db import initialize_database
from .knowledge import ensure_seed_knowledge, load_knowledge_base
from .llm import (
    LLMProviderError,
    OpenAIChatProvider,
    OpenAIWithGrokToolProvider,
    SupportsLLMGenerate,
)
from .models import WatchlistEntry
from .repository import PortfolioRepository


LOGGER = logging.getLogger(__name__)


DEFAULT_WATCHLISTS: dict[str, Sequence[WatchlistEntry]] = {
    "jp": (
        WatchlistEntry("7203.T", "Core mobility leader for EV coverage"),
        WatchlistEntry("6758.T", "Imaging and entertainment exposure"),
        WatchlistEntry("8035.T", "Semiconductor equipment bellwether"),
        WatchlistEntry("9432.T", "Stable telecom cashflow"),
        WatchlistEntry("2914.T", "Consumer staples defensiveness"),
    ),
    "us": (
        WatchlistEntry("AAPL", "Platform ecosystem strength"),
        WatchlistEntry("MSFT", "Cloud and productivity leader"),
        WatchlistEntry("NVDA", "AI infrastructure momentum"),
        WatchlistEntry("TSLA", "EV innovation watch"),
        WatchlistEntry("JNJ", "Healthcare ballast"),
    ),
}


def _create_repository(db_path: str | Path | None) -> PortfolioRepository:
    return PortfolioRepository(db_path)


def _create_gpt_provider() -> SupportsLLMGenerate:
    model = os.environ.get("KABUPILOT_OPENAI_MODEL", "gpt-4o-mini")
    organisation = os.environ.get("OPENAI_ORG")
    return OpenAIChatProvider(model=model, organisation=organisation)


def _create_grok_tool_provider() -> SupportsLLMGenerate | None:
    try:
        model = os.environ.get(
            "KABUPILOT_OPENAI_TOOL_MODEL",
            os.environ.get("KABUPILOT_OPENAI_MODEL", "gpt-4.1"),
        )
        grok_model = os.environ.get("KABUPILOT_XAI_MODEL", "grok-4")
        organisation = os.environ.get("OPENAI_ORG")
        return OpenAIWithGrokToolProvider(
            model=model,
            organisation=organisation,
            grok_model=grok_model,
        )
    except LLMProviderError as exc:
        LOGGER.warning("OpenAI Grok tool provider unavailable: %s", exc)
        return None
def cmd_init_db(args: argparse.Namespace) -> None:
    db_path = initialize_database(args.db_path, force=args.force)
    repository = _create_repository(db_path)

    ensure_seed_knowledge(database_path=db_path)

    # Seed watchlist from the knowledge base to help the Explorer agent.
    market = repository.get_market()
    repository.replace_watchlist(DEFAULT_WATCHLISTS[market])

    print(f"Database initialised at {db_path} (market={market})")


def cmd_show_portfolio(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    market = repository.get_market()
    snapshot = repository.portfolio_snapshot()

    print(f"Configured market: {market}")
    print("Cash balance:", f"${snapshot.cash_balance:,.2f}")
    print("Positions:")
    if snapshot.positions:
        for position in snapshot.positions:
            print(f"  - {position.symbol}: {position.shares:.2f} @ ${position.avg_price:,.2f}")
    else:
        print("  (none)")

    print("Watchlist:")
    if snapshot.watchlist:
        for entry in snapshot.watchlist:
            print(f"  - {entry.symbol}: {entry.note}")
    else:
        print("  (none)")

    recent = repository.list_activity(limit=10)
    print("Recent activity:")
    if recent:
        for activity in recent:
            print(
                f"  - [{activity.timestamp.isoformat()}] {activity.agent} {activity.activity_type}: {activity.summary}"
            )
    else:
        print("  (no activity recorded)")


def cmd_run_planner(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    market = repository.get_market()
    knowledge = load_knowledge_base(market, database_path=args.db_path)
    provider = _create_gpt_provider()
    planner = PlannerAgent(repository, provider, knowledge)
    goal = planner.run(args.week_start)
    print("Planner goal recorded:\n")
    print(goal.content)


def cmd_run_daily(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    market = repository.get_market()
    knowledge = load_knowledge_base(market, database_path=args.db_path)
    provider = _create_gpt_provider()
    grok_provider = _create_grok_tool_provider()
    if not isinstance(grok_provider, OpenAIWithGrokToolProvider):
        raise SystemExit(
            "OpenAIWithGrokToolProvider is required for Grok-integrated explorer and researcher agents."
        )
    explorer = ExplorerAgent(repository, provider, knowledge, grok_provider)
    researcher = ResearcherAgent(provider, knowledge, grok_provider)
    leader = ResearchLeaderAgent(researcher)
    decider = DeciderAgent(repository, provider, knowledge)
    updater = PortfolioUpdaterAgent(explorer, leader, decider, repository)

    print(f"Running daily portfolio update for market '{market}'...\n")
    result = updater.run()

    print("Explorer suggested symbols:")
    print("  ", ", ".join(result["explorer"].symbols))
    print("\nResearch findings:")
    for finding in result["research"]:
        print(f"  - {finding.symbol}: score={finding.score:.2f} :: {finding.rationale}")

    print("\nTransactions executed:")
    if result["transactions"]:
        for tx in result["transactions"]:
            print(f"  - {tx.kind.upper()} {tx.symbol} {tx.shares} @ ${tx.price:,.2f} :: {tx.reason}")
    else:
        print("  (none)")

    if args.result_path:
        serializable_result = {
            "explorer": asdict(result["explorer"]),
            "research": [asdict(item) for item in result["research"]],
            "transactions": [asdict(item) for item in result["transactions"]],
        }
        serializable_result["as_of"] = args.date.isoformat()
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(
            json.dumps(serializable_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nDaily result written to {args.result_path}")

    print("\nRun the 'update-memo' command to refresh the shared memo once reviews are ready.")


def cmd_update_memo(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    market = repository.get_market()
    knowledge = load_knowledge_base(market, database_path=args.db_path)
    provider = _create_gpt_provider()
    checker = CheckerAgent(repository, provider, knowledge, args.db_path)

    daily_result = None
    if args.result_path:
        try:
            with args.result_path.open("r", encoding="utf-8") as handle:
                daily_result = json.load(handle)
        except FileNotFoundError as error:
            raise SystemExit(f"Daily result file not found: {args.result_path}") from error

    as_of = args.date
    if as_of is None and isinstance(daily_result, dict):
        as_of_str = daily_result.get("as_of")
        if as_of_str:
            as_of = datetime.fromisoformat(as_of_str).date()
    if as_of is None:
        as_of = date.today()

    summary = checker.run(as_of, daily_result=daily_result)
    print("Shared memo updated with the following summary:\n")
    print(summary)


def cmd_set_market(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    repository.set_market(args.market)

    if args.refresh_watchlist:
        repository.replace_watchlist(DEFAULT_WATCHLISTS[args.market])

    print(f"Market updated to '{args.market}'")
    if args.refresh_watchlist:
        print("Watchlist refreshed from knowledge base")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="kabupilot backend CLI")
    parser.set_defaults(func=None)

    parser.add_argument(
        "--db-path",
        type=Path,
        default=get_database_path(),
        help="Path to the SQLite database file.",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init-db", help="Initialise the SQLite database")
    init_parser.add_argument("--force", action="store_true", help="Recreate the database if it exists")
    init_parser.set_defaults(func=cmd_init_db)

    show_parser = subparsers.add_parser("show-portfolio", help="Show the current portfolio snapshot")
    show_parser.set_defaults(func=cmd_show_portfolio)

    planner_parser = subparsers.add_parser("run-planner", help="Run the weekly planner agent")
    planner_parser.add_argument(
        "--week-start",
        type=lambda value: datetime.fromisoformat(value).date(),
        default=date.today() - timedelta(days=date.today().weekday()),
        help="ISO formatted date representing the start of the week.",
    )
    planner_parser.set_defaults(func=cmd_run_planner)

    daily_parser = subparsers.add_parser("run-daily", help="Execute the daily portfolio updater")
    daily_parser.add_argument(
        "--date",
        type=lambda value: datetime.fromisoformat(value).date(),
        default=date.today(),
        help="Date for the checker summary (ISO format)",
    )
    daily_parser.add_argument(
        "--result-path",
        type=Path,
        help="Optional path to write the updater result as JSON for memo updates.",
    )
    daily_parser.set_defaults(func=cmd_run_daily)

    market_parser = subparsers.add_parser(
        "set-market",
        help="Update the configured market and optionally refresh the watchlist",
    )
    market_parser.add_argument(
        "market",
        choices=("jp", "us"),
        help="Market identifier to use for subsequent runs",
    )
    market_parser.add_argument(
        "--refresh-watchlist",
        action="store_true",
        help="Re-seed the watchlist from the selected market's knowledge base",
    )
    market_parser.set_defaults(func=cmd_set_market)

    memo_parser = subparsers.add_parser(
        "update-memo",
        help="Update the shared memo using the checker agent",
    )
    memo_parser.add_argument(
        "--date",
        type=lambda value: datetime.fromisoformat(value).date(),
        help="Date associated with the memo update (ISO format)",
    )
    memo_parser.add_argument(
        "--result-path",
        type=Path,
        help="Optional path to load a JSON daily result produced by 'run-daily'.",
    )
    memo_parser.set_defaults(func=cmd_update_memo)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
