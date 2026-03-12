"""Historian — RAG agent providing push briefings and pull queries.

The historian is the read interface to the Knowledge Store. It provides
context to stateless agents so they can work without persistent memory.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentagent.core.agent import Agent, AgentResponse, Message

if TYPE_CHECKING:
    from agentagent.store.repository import Repository

logger = logging.getLogger(__name__)


class Historian:
    """Provides context briefings and answers on-demand queries.

    Push: brief() — proactive context at the start of each round.
    Pull: query() — on-demand answers to agent questions.
    """

    def __init__(self, model: str, repository: Repository, project_id: str) -> None:
        self._model = model
        self._repo = repository
        self._project_id = project_id
        self._agent = Agent(
            role="historian",
            persona=(
                "You are the project historian. You have access to all decisions, "
                "discussion summaries, artifacts, and open questions for this project. "
                "Your job is to provide accurate, concise context to other agents. "
                "When briefing, focus on what is relevant to the current task. "
                "When answering queries, cite specific decisions and their rationale. "
                "If a decision was superseded, explain both the old and new decisions "
                "and why the change happened. Never fabricate information — if you "
                "don't have relevant context, say so."
            ),
            model=model,
        )

    async def brief(self, team: str, task_description: str) -> str:
        """Generate a proactive briefing for a team starting work.

        Retrieves relevant decisions, summaries, artifacts, and open questions,
        then synthesizes a focused briefing.
        """
        # Gather structured context
        decisions = await self._repo.get_active_decisions(self._project_id)
        questions = await self._repo.get_open_questions(self._project_id)
        summaries = await self._repo.get_summaries(self._project_id)

        # Semantic search for task-relevant context
        search_results = self._repo.search(self._project_id, task_description, n_results=5)

        context_parts = []

        if decisions:
            context_parts.append("## Active Decisions")
            for d in decisions:
                confidence_label = f" (confidence: {d.confidence:.0%})" if d.confidence < 1 else ""
                context_parts.append(
                    f"- [{d.team}] {d.topic}: {d.decision_text}{confidence_label}"
                )

        if summaries:
            context_parts.append("\n## Recent Discussion Summaries")
            for s in list(summaries)[-5:]:  # Last 5 summaries
                context_parts.append(
                    f"- [{s.team} R{s.round_number}] {s.topic}: {s.conclusions}"
                )

        if questions:
            context_parts.append("\n## Open Questions")
            for q in questions:
                context_parts.append(f"- [{q.raised_by}] {q.question} (priority: {q.priority})")

        if search_results:
            context_parts.append("\n## Related Context from Semantic Search")
            for r in search_results:
                context_parts.append(f"- {r['text'][:300]}")

        context_text = "\n".join(context_parts) if context_parts else "No prior context. This is the first task."

        messages = [
            Message(
                role="user",
                content=(
                    f"Prepare a briefing for the '{team}' team. Their task is:\n"
                    f"{task_description}\n\n"
                    f"Here is all the relevant project context:\n\n{context_text}\n\n"
                    "Synthesize a concise briefing that highlights:\n"
                    "1. Relevant decisions and constraints\n"
                    "2. Key context from prior discussions\n"
                    "3. Open questions they should be aware of\n"
                    "4. Any superseded decisions they should know about\n"
                    "Keep it focused on what's relevant to their task."
                ),
            )
        ]
        response = await self._agent.run(messages)
        return response.content

    async def query(self, question: str) -> AgentResponse:
        """Answer an on-demand question from any agent.

        Searches the knowledge store semantically and retrieves relevant
        structured records to produce an accurate answer.
        """
        # Search for relevant context
        search_results = self._repo.search(self._project_id, question, n_results=8)
        decisions = await self._repo.get_active_decisions(self._project_id)

        context_parts = ["## Relevant Knowledge Store Results"]
        for r in search_results:
            context_parts.append(f"- [{r['metadata'].get('type', 'unknown')}] {r['text'][:400]}")

        if decisions:
            context_parts.append("\n## All Active Decisions")
            for d in decisions:
                context_parts.append(f"- [{d.team}] {d.topic}: {d.decision_text}")

        context_text = "\n".join(context_parts)

        messages = [
            Message(
                role="user",
                content=(
                    f"An agent has asked the following question:\n\n{question}\n\n"
                    f"Here is the relevant context from the project knowledge store:\n\n"
                    f"{context_text}\n\n"
                    "Answer accurately and concisely. Cite specific decisions or "
                    "discussions. If the information isn't available, say so."
                ),
            )
        ]
        return await self._agent.run(messages)

    async def check_circular(self, topic: str) -> str | None:
        """Check if a topic has been discussed before and return context if so.

        Returns None if the topic hasn't been discussed, or a summary
        of the previous discussion if it has.
        """
        results = self._repo.search(self._project_id, topic, n_results=3)
        if not results or results[0]["distance"] > 0.3:
            return None

        decisions = await self._repo.get_decisions_by_topic(self._project_id, topic)
        if not decisions:
            return None

        parts = [f"This topic has been discussed before:"]
        for d in decisions:
            status = "ACTIVE" if d.status.value == "active" else d.status.value.upper()
            parts.append(f"- [{status}] {d.decision_text} (rationale: {d.rationale})")
        return "\n".join(parts)
