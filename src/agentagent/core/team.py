"""Team container — the fundamental unit of collaboration.

A team holds a moderator, historian, stenographer, and N domain experts.
It implements the team loop: intake → work → compress → output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agentagent.config import TeamConfig
from agentagent.core.agent import Agent, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.historian import Historian
from agentagent.core.moderator import Moderator
from agentagent.core.modes import ModeResult
from agentagent.core.stenographer import Stenographer
from agentagent.store.models import Artifact, ArtifactStatus
from agentagent.store.repository import Repository
from agentagent.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class TeamOutput:
    """Output produced by a team after completing its work."""

    content: str
    artifact: Artifact | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.8
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    rounds_used: int = 0


class Team:
    """A team of AI experts that collaborates on tasks.

    The team follows this loop:
    1. INTAKE: Task arrives → Historian briefs → Moderator selects mode
    2. WORK: Mode-dependent protocol (may be multiple rounds)
    3. COMPRESS: Stenographer records and summarizes
    4. OUTPUT: Package deliverable + decisions + open questions
    """

    def __init__(
        self,
        config: TeamConfig,
        repository: Repository,
        tool_registry: ToolRegistry,
        project_id: str,
        event_bus: EventBus | None = None,
        historian_model: str = "gpt-4o",
        stenographer_model: str = "gpt-4o-mini",
    ) -> None:
        self.name = config.name
        self.purpose = config.purpose
        self._config = config
        self._project_id = project_id
        self._event_bus = event_bus
        self._repo = repository

        # Create domain expert agents
        self._experts: list[Agent] = []
        for expert_cfg in config.experts:
            agent = Agent(
                role=expert_cfg.role,
                persona=expert_cfg.persona,
                model=expert_cfg.model,
                tool_names=expert_cfg.tools,
                tool_registry=tool_registry,
            )
            self._experts.append(agent)

        # Create support agents
        self._moderator = Moderator(
            model=config.moderator_model,
            preferred_modes=config.preferred_modes,
            max_rounds=config.max_rounds,
        )
        self._historian = Historian(
            model=historian_model,
            repository=repository,
            project_id=project_id,
        )
        self._stenographer = Stenographer(
            model=stenographer_model,
            repository=repository,
            project_id=project_id,
        )

    async def execute_task(
        self,
        task: str,
        output_artifact_types: list[str] | None = None,
        gate_criteria: dict[str, Any] | None = None,
    ) -> TeamOutput:
        """Execute a complete task through the team loop.

        Args:
            task: The task description from the workflow or user.
            output_artifact_types: Types of artifacts this team should produce.
            gate_criteria: Acceptance criteria for the gate.

        Returns:
            TeamOutput with the deliverable and metadata.
        """
        total_in = 0
        total_out = 0
        rounds_used = 0

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.TEAM_ROUND_START,
                data={"team": self.name, "task": task[:200]},
                project_id=self._project_id,
            ))

        # ── Phase 1: INTAKE ──
        # Historian briefs the team
        briefing = await self._historian.brief(self.name, task)

        # Check for circular discussions
        circular_check = await self._historian.check_circular(task)
        if circular_check:
            briefing += f"\n\n⚠️ HISTORIAN NOTE: {circular_check}"

        context = (
            f"## Team: {self.name}\n"
            f"## Purpose: {self.purpose}\n\n"
            f"## Historian Briefing:\n{briefing}"
        )

        # ── Phase 2: WORK ──
        last_result: ModeResult | None = None
        for round_num in range(1, self._config.max_rounds + 1):
            rounds_used = round_num

            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.TEAM_ROUND_START,
                    data={"team": self.name, "round": round_num},
                    project_id=self._project_id,
                ))

            # Run a round through the moderator
            result = await self._moderator.run_round(
                agents=self._experts,
                task=task if last_result is None else f"{task}\n\nPrevious round result:\n{last_result.content[:2000]}",
                context=context,
                event_bus=self._event_bus,
                project_id=self._project_id,
            )
            total_in += result.total_input_tokens
            total_out += result.total_output_tokens
            last_result = result

            # ── Phase 3: COMPRESS ──
            # Build transcript from result
            transcript_text = f"Round {round_num} ({self.name}):\n{result.content}"
            await self._stenographer.record_round(
                team=self.name,
                round_number=round_num,
                transcript_text=transcript_text,
                topic=task[:200],
            )

            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.TEAM_ROUND_END,
                    data={
                        "team": self.name,
                        "round": round_num,
                        "confidence": result.confidence,
                    },
                    project_id=self._project_id,
                ))

            # Check completeness
            is_complete, reasoning = await self._moderator.evaluate_completeness(
                task, result, gate_criteria
            )
            if is_complete:
                logger.info(
                    "Team %s completed in round %d: %s", self.name, round_num, reasoning
                )
                break

            # Update context with compressed summary for next round
            context += f"\n\n## Round {round_num} Summary:\n{result.content[:1000]}"

        # ── Phase 4: OUTPUT ──
        if not last_result:
            return TeamOutput(content="No result produced.", rounds_used=rounds_used)

        # Save artifact if configured
        artifact = None
        if output_artifact_types:
            for art_type in output_artifact_types:
                artifact = await self._repo.save_artifact(
                    Artifact(
                        project_id=self._project_id,
                        artifact_type=art_type,
                        name=f"{self.name}_{art_type}",
                        content=last_result.content,
                        team=self.name,
                        status=ArtifactStatus.DRAFT,
                    )
                )
                if self._event_bus:
                    await self._event_bus.emit(Event(
                        type=EventType.ARTIFACT_CREATED,
                        data={
                            "team": self.name,
                            "artifact_type": art_type,
                            "artifact_id": artifact.id,
                        },
                        project_id=self._project_id,
                    ))

        return TeamOutput(
            content=last_result.content,
            artifact=artifact,
            decisions=last_result.decisions,
            open_questions=last_result.open_questions,
            confidence=last_result.confidence,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            rounds_used=rounds_used,
        )
