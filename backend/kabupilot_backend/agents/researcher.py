"""Researcher agent implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, ResearchScore
from ..tools.external import GrokTool, InternetSearchTool


@dataclass
class Researcher(BaseAgent):
    search_tool: InternetSearchTool
    grok_tool: GrokTool

    def run(self, symbol: str) -> Dict[str, object]:
        self.reset_activity()
        headlines = self.search_tool.search_symbol(symbol)
        chatter = self.grok_tool.check_symbol(symbol)
        self.log("internet-search", details=f"Collected {len(headlines)} headlines", metadata={"symbol": symbol})
        self.log("social-check", details=chatter, metadata={"symbol": symbol})

        base_score = 0.5
        if any("upgrade" in headline.lower() for headline in headlines):
            base_score += 0.2
        if any("downgrade" in headline.lower() for headline in headlines):
            base_score -= 0.2
        if "positive" in chatter.lower():
            base_score += 0.1
        if "negative" in chatter.lower():
            base_score -= 0.1

        score = max(0.0, min(1.0, base_score))
        rationale = f"Score derived from qualitative signals; base score {score:.2f}."

        summary = AgentSummary(summary=f"{symbol} scored {score:.2f}", artifacts={"score": score, "rationale": rationale})
        research = ResearchScore(symbol=symbol, score=score, rationale=rationale)

        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
            "score": research.to_json(),
        }
