"""Organic discussion protocol — agent-driven speak-or-PASS model.

Replaces the moderator-directed OPEN→TENSIONS→PROBE→SYNTHESIZE with a
simpler, more natural DISCUSS→SYNTHESIZE loop.  Agents autonomously decide
whether to speak each round — no moderator directs who talks.

When ``prior_output`` is ``None`` the discussion is *thinking* (pre-exec).
When ``prior_output`` is provided it is *reflecting* (post-exec).
The protocol is identical — only the opening prompt and synthesis schema differ.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agentagent.core.agent import Agent, AgentResponse, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.schemas import (
    DiscussionSynthesis,
    ReflectionSynthesis,
    SpiralCheck,
    json_schema_format,
    parse_llm_json,
)

if TYPE_CHECKING:
    from agentagent.core.events import RunContext
    from agentagent.core.historian import Historian

logger = logging.getLogger(__name__)

# Temperature for structured moderator outputs
MODERATOR_TEMPERATURE: float = 0.2

# Sentinel returned by agents who have nothing to add
PASS_SENTINEL = "PASS"

# How often (in rounds) the moderator checks for spiralling
SPIRAL_CHECK_INTERVAL = 3


# ── Data structures ──────────────────────────────────────────


@dataclass
class TranscriptEntry:
    """A single attributed message in a discussion transcript."""

    speaker: str
    role: str
    content: str
    phase: str  # "discuss", "synthesis", "moderator", "historian"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "role": self.role,
            "content": self.content,
            "phase": self.phase,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class DeliberationConfig:
    """Runtime configuration for a single discussion."""

    max_rounds: int = 6
    moderator_temperature: float = MODERATOR_TEMPERATURE
    spiral_check_interval: int = SPIRAL_CHECK_INTERVAL


@dataclass
class DeliberationResult:
    """Output of a completed discussion."""

    transcript: list[TranscriptEntry]
    summary: str
    mode_selection: str | None = None       # pre-exec only
    verdict: str | None = None              # post-exec only ("accept" | "revise")
    revision_guidance: str | None = None    # when verdict == "revise"
    total_input_tokens: int = 0
    total_output_tokens: int = 0


# ── Prompt builders ───────────────────────────────────────────


_SPEAK_OR_PASS = (
    "If you have something NEW to add — a disagreement, a correction, a "
    "critical concern, a nuance, or a perspective not yet represented — "
    "respond with it. Prioritise fundamental issues over minor details. "
    "If your point has already been adequately covered, or you agree and "
    "have nothing to add, respond with exactly: PASS"
)


def _opening_prompt_think(task: str) -> str:
    return (
        f"The team has been assigned this task:\n\n{task}\n\n"
        "Share your initial perspective in 2-3 sentences. "
        "What approach would you take, and what risks or tradeoffs do you see?"
    )


def _opening_prompt_reflect(task: str, prior_output: str) -> str:
    return (
        f"The team produced this output for the task:\n\n"
        f"**Task:** {task}\n\n"
        f"**Output:**\n{prior_output[:3000]}\n\n"
        "In 2-3 sentences, assess the quality of this output. "
        "What works well? What needs revision?"
    )


# ── Transcript helpers ────────────────────────────────────────


def _transcript_to_messages(transcript: list[TranscriptEntry]) -> list[Message]:
    """Convert transcript entries to LLM messages for context."""
    return [
        Message(
            role="user",
            name=entry.speaker,
            content=f"[{entry.role}] {entry.content}",
        )
        for entry in transcript
    ]


def _format_transcript_text(transcript: list[TranscriptEntry]) -> str:
    """Render transcript as readable text for inclusion in prompts."""
    lines: list[str] = []
    for entry in transcript:
        lines.append(f"**{entry.role}** ({entry.speaker}): {entry.content}")
    return "\n\n".join(lines)


def _is_pass(content: str) -> bool:
    """Check if an agent response is a PASS."""
    return content.strip().upper() == PASS_SENTINEL


# ── Core protocol ─────────────────────────────────────────────


async def deliberate(
    moderator_agent: Agent,
    agents: list[Agent],
    task: str,
    context: str,
    historian: "Historian",
    config: DeliberationConfig,
    prior_output: str | None = None,
    event_bus: EventBus | None = None,
    project_id: str = "",
    run_context: "RunContext | None" = None,
) -> DeliberationResult:
    """Run the organic discussion protocol.

    DISCUSS rounds: all agents fire in parallel with the full transcript.
    Round 1 everyone responds; round 2+ agents speak or PASS.
    Convergence when all agents PASS in the same round.
    Moderator checks for spiralling every ``spiral_check_interval`` rounds.

    SYNTHESIZE: moderator produces a structured summary.
    """
    transcript: list[TranscriptEntry] = []
    total_in = 0
    total_out = 0
    is_reflecting = prior_output is not None
    roster = [a.role for a in agents]

    phase_label = "reflect" if is_reflecting else "think"

    if event_bus:
        await event_bus.emit(Event(
            type=EventType.DELIBERATION_START,
            data={"phase": phase_label, "agents": roster, "task": task[:200]},
            project_id=project_id,
        ))

    # Pre-build synthesis format (static, no dynamic roster schema needed)
    synth_format = json_schema_format(
        "DiscussionSynthesis", DiscussionSynthesis.model_json_schema(),
    )
    reflect_format = json_schema_format(
        "ReflectionSynthesis", ReflectionSynthesis.model_json_schema(),
    )
    spiral_format = json_schema_format(
        "SpiralCheck", SpiralCheck.model_json_schema(),
    )

    # ── DISCUSS ───────────────────────────────────────────────
    for round_num in range(1, config.max_rounds + 1):
        if run_context:
            await run_context.check_pause()

        is_first_round = round_num == 1

        # Build the prompt for this round
        if is_first_round:
            if is_reflecting:
                opening = _opening_prompt_reflect(task, prior_output)  # type: ignore[arg-type]
            else:
                opening = _opening_prompt_think(task)
            round_prompt = opening
        else:
            round_prompt = (
                f"Discussion continues.\n\n{_SPEAK_OR_PASS}"
            )

        # Add round prompt to transcript so agents see it
        transcript.append(TranscriptEntry(
            speaker="moderator",
            role="moderator",
            content=round_prompt,
            phase="discuss",
        ))

        # ── Single agent: respond and break ───────────────────
        if len(agents) == 1:
            agent = agents[0]
            resp = await agent.run(
                _transcript_to_messages(transcript),
                run_context=run_context,
            )
            total_in += resp.input_tokens
            total_out += resp.output_tokens

            if not _is_pass(resp.content):
                transcript.append(TranscriptEntry(
                    speaker=agent.role,
                    role=agent.role,
                    content=resp.content,
                    phase="discuss",
                ))
                if event_bus:
                    await event_bus.emit(Event(
                        type=EventType.AGENT_MESSAGE,
                        data={"agent": agent.role, "content": resp.content, "phase": "discuss"},
                        project_id=project_id,
                    ))
            break  # Single agent: one round then synthesize

        # ── Multi-agent: parallel responses ───────────────────
        responses: list[AgentResponse] = await asyncio.gather(
            *[
                agent.run(
                    _transcript_to_messages(transcript),
                    run_context=run_context,
                )
                for agent in agents
            ]
        )

        all_passed = True
        for agent, resp in zip(agents, responses):
            total_in += resp.input_tokens
            total_out += resp.output_tokens

            if _is_pass(resp.content):
                continue  # Silent — don't add to transcript

            all_passed = False
            transcript.append(TranscriptEntry(
                speaker=agent.role,
                role=agent.role,
                content=resp.content,
                phase="discuss",
            ))
            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.AGENT_MESSAGE,
                    data={"agent": agent.role, "content": resp.content, "phase": "discuss"},
                    project_id=project_id,
                ))

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.DELIBERATION_CYCLE,
                data={
                    "round": round_num,
                    "converged": all_passed and not is_first_round,
                    "speakers": sum(1 for _, r in zip(agents, responses) if not _is_pass(r.content)),
                    "phase": phase_label,
                },
                project_id=project_id,
            ))

        # Convergence: all agents PASS'd (but not on round 1)
        if all_passed and not is_first_round:
            logger.info("Discussion converged — all agents passed in round %d", round_num)
            break

        # ── Spiralling check ──────────────────────────────────
        if (
            round_num > 1
            and round_num % config.spiral_check_interval == 0
        ):
            spiral_tokens_in, spiral_tokens_out = await _check_spiral(
                moderator_agent=moderator_agent,
                transcript=transcript,
                task=task,
                historian=historian,
                spiral_format=spiral_format,
                config=config,
                event_bus=event_bus,
                project_id=project_id,
            )
            total_in += spiral_tokens_in
            total_out += spiral_tokens_out

    # ── SYNTHESIZE ────────────────────────────────────────────
    synthesis_context = (
        f"Task: {task}\n\n"
        f"Context: {context}\n\n"
        f"Full discussion transcript:\n{_format_transcript_text(transcript)}"
    )

    if not is_reflecting:
        synth_prompt = (
            f"{synthesis_context}\n\n"
            "Synthesise the team's discussion into a pre-execution summary. "
            "Identify the consensus, any open items, and select the best "
            "interaction mode for execution."
        )
        synth_resp = await moderator_agent.run(
            [Message(role="user", content=synth_prompt)],
            response_format=synth_format,
            temperature=config.moderator_temperature,
        )
        total_in += synth_resp.input_tokens
        total_out += synth_resp.output_tokens
        synth = parse_llm_json(synth_resp.content, DiscussionSynthesis)

        transcript.append(TranscriptEntry(
            speaker="moderator", role="moderator",
            content=synth.summary, phase="synthesis",
        ))

        result = DeliberationResult(
            transcript=transcript,
            summary=synth.summary,
            mode_selection=synth.mode_selection,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
        )
    else:
        synth_prompt = (
            f"{synthesis_context}\n\n"
            f"The team produced this output:\n{prior_output[:3000]}\n\n"  # type: ignore[index]
            "Synthesise the team's reflection. Should the output be accepted "
            "as-is, or does it need revision? If revision is needed, provide "
            "specific guidance on what to fix."
        )
        synth_resp = await moderator_agent.run(
            [Message(role="user", content=synth_prompt)],
            response_format=reflect_format,
            temperature=config.moderator_temperature,
        )
        total_in += synth_resp.input_tokens
        total_out += synth_resp.output_tokens
        synth = parse_llm_json(synth_resp.content, ReflectionSynthesis)

        transcript.append(TranscriptEntry(
            speaker="moderator", role="moderator",
            content=synth.summary, phase="synthesis",
        ))

        result = DeliberationResult(
            transcript=transcript,
            summary=synth.summary,
            verdict=synth.verdict,
            revision_guidance=synth.revision_guidance or None,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
        )

    if event_bus:
        await event_bus.emit(Event(
            type=EventType.DELIBERATION_COMPLETE,
            data={
                "phase": phase_label,
                "summary": result.summary[:200],
                "verdict": result.verdict,
                "mode_selection": result.mode_selection,
            },
            project_id=project_id,
        ))

    return result


async def _check_spiral(
    *,
    moderator_agent: Agent,
    transcript: list[TranscriptEntry],
    task: str,
    historian: "Historian",
    spiral_format: dict[str, Any],
    config: DeliberationConfig,
    event_bus: EventBus | None,
    project_id: str,
) -> tuple[int, int]:
    """Moderator health check: is the discussion making progress?

    If circular, injects a convergence nudge into the transcript.
    Returns (input_tokens, output_tokens) consumed.
    """
    prompt = (
        f"You are monitoring a team discussion.\n\n"
        f"Task: {task}\n\n"
        f"Transcript:\n{_format_transcript_text(transcript)}\n\n"
        "Is this discussion making progress, or are the participants "
        "repeating the same arguments? If circular, suggest a redirect topic "
        "to move forward."
    )
    resp = await moderator_agent.run(
        [Message(role="user", content=prompt)],
        response_format=spiral_format,
        temperature=config.moderator_temperature,
    )
    check = parse_llm_json(resp.content, SpiralCheck)

    if check.is_circular:
        nudge = (
            f"The discussion appears to be going in circles: {check.reason} "
        )
        if check.redirect_topic:
            nudge += f"Let's refocus on: {check.redirect_topic} "
        nudge += "Converge on a position or explicitly agree to disagree."

        transcript.append(TranscriptEntry(
            speaker="moderator", role="moderator",
            content=nudge, phase="moderator",
        ))
        logger.info("Spiral detected — injected convergence nudge")

        # Also check historian for circular decisions
        try:
            circular = await historian.check_circular(task)
            if circular:
                transcript.append(TranscriptEntry(
                    speaker="historian", role="historian",
                    content=f"Prior decision exists: {circular}",
                    phase="historian",
                ))
        except Exception:
            pass

    return resp.input_tokens, resp.output_tokens


# ── Conversation variant (for targeted user conversations) ────


async def converse_with_team(
    moderator_agent: Agent,
    agents: list[Agent],
    user_message: str,
    context: str,
    historian: "Historian",
    config: DeliberationConfig,
    event_bus: EventBus | None = None,
    project_id: str = "",
    run_context: "RunContext | None" = None,
) -> DeliberationResult:
    """Run an organic team discussion triggered by a user question.

    Thin wrapper around ``deliberate()`` — the user's message becomes
    the task, and we run in thinking mode (no prior_output).
    """
    return await deliberate(
        moderator_agent=moderator_agent,
        agents=agents,
        task=user_message,
        context=context,
        historian=historian,
        config=config,
        prior_output=None,
        event_bus=event_bus,
        project_id=project_id,
        run_context=run_context,
    )
