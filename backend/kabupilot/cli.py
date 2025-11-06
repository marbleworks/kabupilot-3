"""Command line interface for the kabupilot backend."""

from __future__ import annotations

import argparse
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
from .models import WatchlistEntry
from .repository import PortfolioRepository


def _create_repository(db_path: str | Path | None) -> PortfolioRepository:
    return PortfolioRepository(db_path)


def cmd_init_db(args: argparse.Namespace) -> None:
    db_path = initialize_database(args.db_path, force=args.force)
    repository = _create_repository(db_path)

    ensure_seed_knowledge(database_path=db_path)

    # Seed watchlist from the knowledge base to help the Explorer agent.
    market = repository.get_market()
    knowledge = load_knowledge_base(market, database_path=db_path)
    repository.replace_watchlist(
        WatchlistEntry(entry.symbol, f"Seed from knowledge base ({entry.sector})")
        for entry in knowledge[:5]
    )

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
    planner = PlannerAgent(repository)
    goal = planner.run(args.week_start)
    print("Planner goal recorded:\n")
    print(goal.content)


def cmd_run_daily(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    market = repository.get_market()
    knowledge = load_knowledge_base(market, database_path=args.db_path)
    explorer = ExplorerAgent(repository, knowledge)
    researcher = ResearcherAgent(knowledge)
    leader = ResearchLeaderAgent(researcher)
    decider = DeciderAgent(repository, knowledge)
    updater = PortfolioUpdaterAgent(explorer, leader, decider, repository)
    checker = CheckerAgent(repository, knowledge)

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

    summary = checker.run(args.date)
    print("\nDaily checker summary:\n")
    print(summary)


def cmd_set_market(args: argparse.Namespace) -> None:
    repository = _create_repository(args.db_path)
    repository.set_market(args.market)

    if args.refresh_watchlist:
        knowledge = load_knowledge_base(args.market, database_path=args.db_path)
        repository.replace_watchlist(
            WatchlistEntry(entry.symbol, f"Seed from knowledge base ({entry.sector})")
            for entry in knowledge[:5]
        )

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
