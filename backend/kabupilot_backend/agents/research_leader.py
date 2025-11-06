"""ResearchLeader coordinates the Researcher agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..core.base_agent import BaseAgent
from ..core.types import AgentSummary, ResearchScore
from ..tools.external import GrokTool, InternetSearchTool
from ..tools.knowledge_base import KnowledgeBase
from .researcher import Researcher


@dataclass
class ResearchLeader(BaseAgent):
    knowledge_base: KnowledgeBase
    search_tool: InternetSearchTool
    grok_tool: GrokTool

    def _spawn_researcher(self) -> Researcher:
        return Researcher(name="Researcher", search_tool=self.search_tool, grok_tool=self.grok_tool)

    def run(self, symbols: List[str]) -> Dict[str, object]:
        self.reset_activity()
        self.log("knowledge-base", details="Consulting recent knowledge entries")
        kb_entries = self.knowledge_base.latest(limit=3)
        for entry in kb_entries:
            self.log("kb-entry", details=entry.title)

        scores: List[ResearchScore] = []
        researcher_logs: Dict[str, List[Dict[str, object]]] = {}
        for symbol in symbols:
            researcher = self._spawn_researcher()
            result = researcher.run(symbol)
            score_payload = result["score"]
            score = ResearchScore(symbol=score_payload["symbol"], score=score_payload["score"], rationale=score_payload["rationale"])
            scores.append(score)
            researcher_logs[symbol] = result["activity"]
            self.log("research", details=f"Completed research for {symbol}", metadata={"score": score.score})

        scores.sort(key=lambda item: item.score, reverse=True)
        summary = AgentSummary(
            summary=f"Researched {len(scores)} symbols. Top candidate: {scores[0].symbol if scores else 'N/A'}",
            artifacts={"scores": [score.to_json() for score in scores], "research_logs": researcher_logs},
        )
        return {
            "summary": summary.to_json(),
            "activity": self.activity_json(),
        }
