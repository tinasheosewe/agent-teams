"""Team container — the fundamental unit of collaboration.

A team holds a moderator, historian, stenographer, and N domain experts.
It implements the team loop: intake → work → compress → output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentagent.config import TeamConfig
from agentagent.core.agent import Agent, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.historian import Historian
from agentagent.core.moderator import Moderator
from agentagent.core.stenographer import Stenographer
from agentagent.store.models import Artifact, ArtifactStatus
from agentagent.store.repository import Repository
from agentagent.tools.base import ToolRegistry

if TYPE_CHECKING:
    from agentagent.core.events import RunContext

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

    The team delegates the full work loop to the Moderator:
    1. INTAKE: Task arrives → Historian briefs the team
    2. WORK: Moderator runs deliberate → execute → deliberate loop
    3. COMPRESS: Stenographer records via moderator recess
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

        # Create historian first — needed for AskHistorianTool
        self._historian = Historian(
            model=historian_model,
            repository=repository,
            project_id=project_id,
        )

        # Register AskHistorianTool if not already present
        from agentagent.tools.builtin import AskHistorianTool
        if not tool_registry.get("ask_historian"):
            tool_registry.register(AskHistorianTool(self._historian))

        # Create domain expert agents
        self._experts: list[Agent] = []
        for expert_cfg in config.experts:
            # Ensure every expert has access to ask_historian
            tools = list(expert_cfg.tools)
            if "ask_historian" not in tools:
                tools.append("ask_historian")
            agent = Agent(
                role=expert_cfg.role,
                persona=expert_cfg.persona,
                model=expert_cfg.model,
                tool_names=tools,
                tool_registry=tool_registry,
            )
            self._experts.append(agent)

        # Create support agents
        self._moderator = Moderator(
            model=config.moderator_model,
            preferred_modes=config.preferred_modes,
            max_rounds=config.max_rounds,
            enable_deliberation=config.enable_deliberation,
            thinking_depth=config.thinking_depth,
            max_deliberation_cycles=config.max_deliberation_cycles,
        )
        self._stenographer = Stenographer(
            model=stenographer_model,
            repository=repository,
            project_id=project_id,
        )

    @property
    def experts(self) -> list[Agent]:
        """Expose domain expert agents for conversation access."""
        return self._experts

    @property
    def historian(self) -> Historian:
        """Expose historian for conversation context."""
        return self._historian

    @property
    def moderator_agent(self) -> Moderator:
        """Expose moderator for synthesis in conversations."""
        return self._moderator

    async def execute_task(
        self,
        task: str,
        output_artifact_types: list[str] | None = None,
        gate_criteria: dict[str, Any] | None = None,
        run_context: "RunContext | None" = None,
    ) -> TeamOutput:
        self,
        task: str,
        output_artifact_types: list[str] | None = None,
        gate_criteria: dict[str, Any] | None = None,
        run_context: "RunContext | None" = None,
    ) -> TeamOutput:
        """Execute a complete task through the team loop.

        Args:
            task: The task description from the workflow or user.
            output_artifact_types: Types of artifacts this team should produce.
            gate_criteria: Acceptance criteria for the gate.
            run_context: Shared context for pause/cancel/event support.

        Returns:
            TeamOutput with the deliverable and metadata.
        """
        # ── Phase 1: INTAKE ──
        try:
            briefing = await self._historian.brief(self.name, task)
        except Exception:
            logger.warning("Historian briefing failed for team %s, proceeding without context", self.name)
            briefing = "No prior context available (historian unavailable)."

        try:
            circular_check = await self._historian.check_circular(task)
        except Exception:
            logger.warning("Historian circular check failed for team %s", self.name)
            circular_check = None
        if circular_check:
            briefing += f"\n\n⚠️ HISTORIAN NOTE: {circular_check}"

        context = (
            f"## Team: {self.name}\n"
            f"## Purpose: {self.purpose}\n\n"
            f"## Historian Briefing:\n{briefing}"
        )

        # ── Phase 2+3: WORK + COMPRESS (delegated to moderator) ──
        loop_result = await self._moderator.run_task_loop(
            agents=self._experts,
            task=task,
            context=context,
            historian=self._historian,
            stenographer=self._stenographer,
            event_bus=self._event_bus,
            project_id=self._project_id,
            run_context=run_context,
        )

        # ── Phase 4: OUTPUT ──
        artifact = None
        if output_artifact_types:
            for art_type in output_artifact_types:
                artifact = await self._repo.save_artifact(
                    Artifact(
                        project_id=self._project_id,
                        artifact_type=art_type,
                        name=f"{self.name}_{art_type}",
                        content=loop_result.content,
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
            content=loop_result.content,
            artifact=artifact,
            decisions=loop_result.decisions,
            open_questions=loop_result.open_questions,
            confidence=loop_result.confidence,
            total_input_tokens=loop_result.total_input_tokens,
            total_output_tokens=loop_result.total_output_tokens,
            rounds_used=loop_result.rounds_used,
        )
