"""Command line entry point to exercise the automation workflow."""
from __future__ import annotations

import json
from typing import Any, Dict

from .workflow import PortfolioAutomationSystem


def run_demo() -> Dict[str, Any]:
    system = PortfolioAutomationSystem()
    weekly_plan = system.plan_week()
    weekly_goal = weekly_plan["summary"]["artifacts"]["weekly_goal"]

    day_result = system.run_trading_day(weekly_goal["daily_goals"][0])
    checker_result = system.review_day(day_result["activity"], weekly_goal)

    return {
        "weekly_plan": weekly_plan,
        "day_result": day_result,
        "review": checker_result,
    }


def main() -> None:
    report = run_demo()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
