"""Moderator — outer loop controller for deliberate → execute → deliberate.

The moderator orchestrates the full team workflow:
1. THINK: Deliberate on approach (pre-execution, single ``deliberate()`` call)
2. EXECUTE: Run the selected mode protocol
3. REFLECT: Deliberate on output quality (post-execution)
4. Loop or accept based on reflection verdict

Reflection outputs are either *revisions* (re-execute) or *conclusions*
(accept).  There is no separate "revise" phase — reflection IS the mechanism
that produces revision instructions when needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentagent.config import InteractionMode, ThinkingDepth
from agentagent.core.agent import Agent, Message
from agentagent.core.deliberation import (
    DeliberationConfig,
    DeliberationResult,
    TranscriptEntry,
    deliberate,
)
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.modes import MODE_MAP, ModeResult

if TYPE_CHECKING:
    from agentagent.core.events import RunContext
    from agentagent.core.historian import Historian
    from agentagent.core.stenographer import Stenographer

logger = logging.getLogger(__name__)


# ── Result container ──────────────────────────────────────────


@dataclass
class LoopResult:
    """Output of the full moderator work loop."""

    content: str
    decisions: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.8
    artifact: Any | None = None

    # Phase-level token tracking
    thinking_tokens: tuple[int, int] = (0, 0)    # (input, output)
    execution_tokens: tuple[int, int] = (0, 0)
    reflection_tokens: tuple[int, int] = (0, 0)

    rounds_used: int = 0
    transcript: list[TranscriptEntry] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return self.thinking_tokens[0] + self.execution_tokens[0] + self.reflection_tokens[0]

    @property
    def total_output_tokens(self) -> int:
        return self.thinking_tokens[1] + self.execution_tokens[1] + self.reflection_tokens[1]


# ── Moderator ─────────────────────────────────────────────────


class Moderator:
    """Orchestrates the deliberate → execute → deliberate loop.

    Replaces the old keyword-router moderator with a genuine loop
    controller that uses the deliberation protocol for both thinking
    and reflecting.
    """

    def __init__(
        self,
        model: str,
        preferred_modes: list[InteractionMode],
        max_rounds: int = 10,
        context_token_limit: int = 80_000,
        enable_deliberation: bool = False,
        thinking_depth: ThinkingDepth = ThinkingDepth.FULL,
        max_deliberation_cycles: int = 3,
    ) -> None:
        self._model = model
        self._preferred_modes = [m.value for m in preferred_modes]
        self._max_rounds = max_rounds
        self._context_token_limit = context_token_limit
        self._enable_deliberation = enable_deliberation
        self._thinking_depth = thinking_depth
        self._max_deliberation_cycles = max_deliberation_cycles

        self._agent = Agent(
            role="moderator",
            persona=(
                "You are a discussion facilitator for a team of experts. "
                "Your job: set the topic, detect when the discussion is "
                "spiralling, and synthesise the team's conclusions. You do "
                "not direct who speaks — the agents decide for themselves."
            ),
            model=model,
        )

    # ── Public API ────────────────────────────────────────────

    async def run_task_loop(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        historian: "Historian",
        stenographer: "Stenographer",
        event_bus: EventBus | None = None,
        project_id: str = "",
        run_context: "RunContext | None" = None,
    ) -> LoopResult:
        """Execute the full deliberate → execute → deliberate loop.

        Returns a ``LoopResult`` with the final output, full transcript,
        and per-phase token tracking.
        """
        if not self._enable_deliberation:
            return await self._run_legacy(
                agents, task, context, event_bus, project_id, run_context,
            )

        return await self._run_deliberation_loop(
            agents, task, context, historian, stenographer,
            event_bus, project_id, run_context,
        )

    def should_compress(self, estimated_tokens: int) -> bool:
        """Check if context is getting too large and needs compression."""
        return estimated_tokens > self._context_token_limit * 0.75

    # ── Deliberation loop ─────────────────────────────────────

    async def _run_deliberation_loop(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        historian: "Historian",
        stenographer: "Stenographer",
        event_bus: EventBus | None,
        project_id: str,
        run_context: "RunContext | None",
    ) -> LoopResult:
        """The core loop: think once → [execute → reflect]* → recess."""
        delib_config = DeliberationConfig(
            max_rounds=self._max_deliberation_cycles * 2,
        )
        full_transcript: list[TranscriptEntry] = []
        think_in = think_out = 0
        exec_in = exec_out = 0
        reflect_in = reflect_out = 0

        # ── 1. THINK (once, not counted as a round) ───────────
        think_result = await deliberate(
            moderator_agent=self._agent,
            agents=agents,
            task=task,
            context=context,
            historian=historian,
            config=delib_config,
            prior_output=None,
            event_bus=event_bus,
            project_id=project_id,
            run_context=run_context,
        )
        full_transcript.extend(think_result.transcript)
        think_in += think_result.total_input_tokens
        think_out += think_result.total_output_tokens

        # Select mode from deliberation synthesis
        mode_name = think_result.mode_selection or self._preferred_modes[0]
        mode = MODE_MAP.get(mode_name)
        if not mode:
            logger.error("Unknown mode %r from deliberation, falling back to generative", mode_name)
            mode = MODE_MAP["generative"]
            mode_name = "generative"

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.TEAM_MODE_SELECTED,
                data={"mode": mode_name, "task": task[:200], "source": "deliberation"},
                project_id=project_id,
            ))

        guidance = think_result.summary
        last_exec_result: ModeResult | None = None
        rounds_used = 0

        # ── 2. EXECUTE → REFLECT loop ─────────────────────────
        for round_num in range(1, self._max_rounds + 1):
            rounds_used = round_num

            if run_context:
                await run_context.check_pause()

            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.TEAM_ROUND_START,
                    data={"round": round_num, "mode": mode_name},
                    project_id=project_id,
                ))

            # Execute
            exec_task = f"{task}\n\n## Deliberation Guidance:\n{guidance}"
            exec_result = await mode.execute(
                agents=agents,
                task=exec_task,
                context=context,
                event_bus=event_bus,
                project_id=project_id,
                run_context=run_context,
            )
            exec_in += exec_result.total_input_tokens
            exec_out += exec_result.total_output_tokens
            last_exec_result = exec_result

            # Convert mode contributions to transcript entries
            for contrib in exec_result.attributed_contributions:
                full_transcript.append(TranscriptEntry(
                    speaker=contrib["agent"],
                    role=contrib["agent"],
                    content=contrib["content"],
                    phase="execute",
                ))

            # Reflect
            reflect_result = await deliberate(
                moderator_agent=self._agent,
                agents=agents,
                task=task,
                context=context,
                historian=historian,
                config=delib_config,
                prior_output=exec_result.content,
                event_bus=event_bus,
                project_id=project_id,
                run_context=run_context,
            )
            full_transcript.extend(reflect_result.transcript)
            reflect_in += reflect_result.total_input_tokens
            reflect_out += reflect_result.total_output_tokens

            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.TEAM_ROUND_END,
                    data={
                        "round": round_num,
                        "verdict": reflect_result.verdict,
                        "confidence": exec_result.confidence,
                    },
                    project_id=project_id,
                ))

            if reflect_result.verdict == "accept":
                logger.info("Team accepted output in round %d", round_num)
                break

            # Revisions: feed reflection guidance back to execution
            guidance = reflect_result.revision_guidance or reflect_result.summary
            logger.info(
                "Round %d: revisions requested — %s",
                round_num, guidance[:100],
            )

        # ── 3. RECESS ─────────────────────────────────────────
        if last_exec_result is None:
            return LoopResult(content="No result produced.", rounds_used=rounds_used)

        # Compress transcript via stenographer
        transcript_text = "\n\n".join(
            f"[{e.phase}] {e.role}: {e.content}" for e in full_transcript
        )
        try:
            await stenographer.record_round(
                team="deliberation",
                round_number=rounds_used,
                transcript_text=transcript_text,
                topic=task[:200],
            )
        except Exception:
            logger.error("Stenographer failed to record deliberation transcript")

        return LoopResult(
            content=last_exec_result.content,
            decisions=last_exec_result.decisions,
            open_questions=last_exec_result.open_questions,
            confidence=last_exec_result.confidence,
            thinking_tokens=(think_in, think_out),
            execution_tokens=(exec_in, exec_out),
            reflection_tokens=(reflect_in, reflect_out),
            rounds_used=rounds_used,
            transcript=full_transcript,
        )

    # ── Legacy path (deliberation disabled) ───────────────────

    async def _run_legacy(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None,
        project_id: str,
        run_context: "RunContext | None",
    ) -> LoopResult:
        """Non-deliberation path: direct mode selection and execution.

        Uses first preferred mode and runs a single round.
        """
        mode_name = self._preferred_modes[0] if self._preferred_modes else "generative"
        mode = MODE_MAP.get(mode_name, MODE_MAP["generative"])

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.TEAM_MODE_SELECTED,
                data={"mode": mode_name, "task": task[:200], "source": "legacy"},
                project_id=project_id,
            ))

        result = await mode.execute(
            agents=agents,
            task=task,
            context=context,
            event_bus=event_bus,
            project_id=project_id,
            run_context=run_context,
        )

        return LoopResult(
            content=result.content,
            decisions=result.decisions,
            open_questions=result.open_questions,
            confidence=result.confidence,
            execution_tokens=(result.total_input_tokens, result.total_output_tokens),
            rounds_used=1,
        )
