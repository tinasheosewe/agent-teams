"""Stenographer — compresses discussions, writes to the Knowledge Store.

The stenographer is the write interface to the Knowledge Store. It records
transcripts, produces summaries, and extracts decisions and open questions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentagent.core.agent import Agent, Message
from agentagent.core.schemas import JSON_MODE, StenographerExtraction, parse_llm_json
from agentagent.store.models import (
    Decision,
    DecisionStatus,
    DiscussionSummary,
    OpenQuestion,
    Transcript,
)

if TYPE_CHECKING:
    from agentagent.store.repository import Repository

logger = logging.getLogger(__name__)


class Stenographer:
    """Records, compresses, and structures team discussions.

    After each round, the stenographer:
    1. Saves the raw transcript
    2. Produces a structured summary
    3. Extracts any decisions made
    4. Extracts any open questions raised
    """

    def __init__(self, model: str, repository: Repository, project_id: str) -> None:
        self._model = model
        self._repo = repository
        self._project_id = project_id
        self._agent = Agent(
            role="stenographer",
            persona=(
                "You are a precise stenographer. You analyze team discussions and produce "
                "structured outputs. You extract:\n"
                "1. Key points discussed\n"
                "2. Conclusions reached\n"
                "3. Specific decisions made (with rationale)\n"
                "4. Open questions raised\n"
                "5. Unresolved items\n\n"
                "Always output valid JSON. Be precise and concise. Never add information "
                "that wasn't in the discussion. Capture the team's actual reasoning."
            ),
            model=model,
        )

    async def record_round(
        self,
        team: str,
        round_number: int,
        transcript_text: str,
        topic: str,
    ) -> DiscussionSummary:
        """Record a discussion round: save transcript, produce summary, extract decisions.

        Returns the DiscussionSummary for the round.
        """
        # 1. Save raw transcript
        await self._repo.save_transcript(
            Transcript(
                project_id=self._project_id,
                team=team,
                round_number=round_number,
                content=transcript_text,
            )
        )

        # 2. Ask the LLM to produce structured extraction
        messages = [
            Message(
                role="user",
                content=(
                    f"Analyze this discussion from the '{team}' team (round {round_number}).\n"
                    f"Topic: {topic}\n\n"
                    f"--- TRANSCRIPT ---\n{transcript_text}\n--- END TRANSCRIPT ---\n\n"
                    "Produce a JSON object with these exact keys:\n"
                    '{\n'
                    '  "key_points": "bullet-point summary of key points discussed",\n'
                    '  "conclusions": "what the team concluded",\n'
                    '  "unresolved_items": "anything left unresolved",\n'
                    '  "decisions": [\n'
                    '    {\n'
                    '      "topic": "the specific topic decided",\n'
                    '      "decision": "what was decided",\n'
                    '      "rationale": "why",\n'
                    '      "confidence": 0.8\n'
                    '    }\n'
                    '  ],\n'
                    '  "open_questions": [\n'
                    '    {\n'
                    '      "question": "the question",\n'
                    '      "raised_by": "who raised it",\n'
                    '      "priority": "high|medium|low"\n'
                    '    }\n'
                    '  ]\n'
                    '}\n\n'
                    "Return ONLY the JSON object, no markdown formatting."
                ),
            )
        ]
        response = await self._agent.run(messages, response_format=JSON_MODE)

        # Parse the structured output
        try:
            data = parse_llm_json(response.content, StenographerExtraction)
        except (ValidationError, ValueError):
            logger.warning("Failed to parse stenographer output, using raw content")
            data = StenographerExtraction(
                key_points=response.content,
                conclusions="",
            )

        # 3. Save discussion summary
        summary = await self._repo.save_summary(
            DiscussionSummary(
                project_id=self._project_id,
                team=team,
                round_number=round_number,
                topic=topic,
                key_points=data.key_points,
                conclusions=data.conclusions,
                unresolved_items=data.unresolved_items,
            )
        )

        # 4. Save extracted decisions
        for dec in data.decisions:
            await self._repo.save_decision(
                Decision(
                    project_id=self._project_id,
                    topic=dec.topic or topic,
                    decision_text=dec.decision,
                    rationale=dec.rationale,
                    team=team,
                    round_number=round_number,
                    status=DecisionStatus.ACTIVE,
                    confidence=dec.confidence,
                )
            )

        # 5. Save extracted open questions
        for q in data.open_questions:
            await self._repo.save_question(
                OpenQuestion(
                    project_id=self._project_id,
                    question=q.question,
                    raised_by=q.raised_by or team,
                    priority=q.priority,
                )
            )

        return summary

    def estimate_token_count(self, messages: list[Message]) -> int:
        """Rough estimate of token count for context management.

        Uses the ~4 chars per token heuristic. Good enough for deciding
        when to trigger a context reset.
        """
        total_chars = sum(len(m.content) for m in messages)
        return total_chars // 4
