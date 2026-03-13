"""Board-based deliberation protocol — rapid-fire round-robin debate.

Agents collaborate through a shared **deliberation board** of versioned
points.  Each agent takes a turn, reads the current board, and responds
with structured actions:

- **Raise** a new point (claim + reasoning).
- **React** to an existing point (agree / disagree / question).
- **Amend** an existing point (new claim text + reason for change).
  Amendments bump the point's version and invalidate prior reactions.
- **Done** — the agent has nothing more to add.

Convergence occurs when every agent declares ``done`` in consecutive
turns *and* no points remain in ``open`` status.

When ``prior_output`` is ``None`` the discussion is *thinking* (pre-exec).
When ``prior_output`` is provided it is *reflecting* (post-exec).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from agentagent.core.agent import Agent, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.schemas import (
    BoardTurnResponse,
    DiscussionSynthesis,
    ReflectionSynthesis,
    json_schema_format,
    parse_llm_json,
)

if TYPE_CHECKING:
    from agentagent.core.events import RunContext
    from agentagent.core.historian import Historian

logger = logging.getLogger(__name__)

# Temperature for structured moderator outputs
MODERATOR_TEMPERATURE: float = 0.2


# ── Board data model ──────────────────────────────────────────


class PointStatus(str, Enum):
    OPEN = "open"
    CONSENSUS = "consensus"
    CONTESTED = "contested"


class Stance(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    QUESTION = "question"


@dataclass
class Reaction:
    """A single agent's reaction to a specific point version."""

    agent: str
    stance: Stance
    reasoning: str


@dataclass
class PointVersion:
    """One version of a point's claim."""

    version: int
    claim: str
    amended_by: str
    amendment_reason: str | None = None
    reactions: dict[str, Reaction] = field(default_factory=dict)


@dataclass
class Point:
    """A single debatable point on the board."""

    id: int
    author: str
    versions: list[PointVersion] = field(default_factory=list)

    @property
    def current(self) -> PointVersion:
        return self.versions[-1]

    @property
    def current_version(self) -> int:
        return self.current.version

    def status(self, roster: list[str]) -> PointStatus:
        """Compute status based on reactions to the current version."""
        reactions = self.current.reactions
        others = [r for r in roster if r != self.author]
        if not others:
            # Single-agent case: point is automatically consensus
            return PointStatus.CONSENSUS
        if any(r.stance == Stance.DISAGREE for r in reactions.values()):
            return PointStatus.CONTESTED
        # Consensus requires all other agents to have reacted (agree or question)
        reacted = {role for role in reactions if role in others}
        if reacted >= set(others):
            return PointStatus.CONSENSUS
        return PointStatus.OPEN

    def amend(self, new_claim: str, amended_by: str, reason: str) -> None:
        """Create a new version, invalidating all prior reactions."""
        new_ver = PointVersion(
            version=self.current_version + 1,
            claim=new_claim,
            amended_by=amended_by,
            amendment_reason=reason,
        )
        self.versions.append(new_ver)

    def react(self, agent: str, stance: Stance, reasoning: str) -> None:
        """Record an agent's reaction to the current version."""
        self.current.reactions[agent] = Reaction(
            agent=agent, stance=stance, reasoning=reasoning,
        )


@dataclass
class Board:
    """The shared deliberation board — the single source of truth."""

    points: list[Point] = field(default_factory=list)
    _next_id: int = 1

    def add_point(self, claim: str, author: str) -> Point:
        point = Point(
            id=self._next_id,
            author=author,
            versions=[PointVersion(version=1, claim=claim, amended_by=author)],
        )
        self._next_id += 1
        self.points.append(point)
        return point

    def get_point(self, point_id: int) -> Point | None:
        for p in self.points:
            if p.id == point_id:
                return p
        return None

    def all_status(self, roster: list[str]) -> dict[int, PointStatus]:
        return {p.id: p.status(roster) for p in self.points}

    def is_settled(self, roster: list[str]) -> bool:
        """True when no points are in OPEN status."""
        return all(
            s != PointStatus.OPEN for s in self.all_status(roster).values()
        )

    def render(self, roster: list[str], *, compact_consensus: bool = True) -> str:
        """Render the board as a text document for inclusion in prompts.

        Settled (consensus) points are rendered compactly.  Open and
        contested points show the full version history and reactions.
        """
        if not self.points:
            return "(Board is empty -- no points raised yet.)"

        lines: list[str] = []
        statuses = self.all_status(roster)

        for point in self.points:
            status = statuses[point.id]
            current = point.current

            if compact_consensus and status == PointStatus.CONSENSUS and len(point.versions) == 1:
                lines.append(
                    f"POINT {point.id}: \"{current.claim}\" [{point.author}] "
                    f"-- CONSENSUS"
                )
                continue

            # Full rendering for open, contested, or amended consensus
            lines.append(
                f"POINT {point.id} (v{current.version}): "
                f"\"{current.claim}\" [{point.author}]"
            )

            # Show version history if amended
            if len(point.versions) > 1:
                for ver in point.versions[:-1]:
                    lines.append(
                        f"  (v{ver.version}, prior): \"{ver.claim}\" "
                        f"[by {ver.amended_by}]"
                    )
                if current.amendment_reason:
                    lines.append(
                        f"  (amended by {current.amended_by}: "
                        f"{current.amendment_reason})"
                    )

            # Show reactions to current version
            for role in roster:
                reaction = current.reactions.get(role)
                if reaction:
                    icon = {"agree": "+", "disagree": "x", "question": "?"}[
                        reaction.stance.value
                    ]
                    lines.append(
                        f"  {icon} {reaction.agent} -- \"{reaction.reasoning}\""
                    )

            lines.append(f"  STATUS: {status.value}")

        return "\n".join(lines)


# ── Transcript (kept for backward compatibility) ──────────────


@dataclass
class TranscriptEntry:
    """A single attributed message in a discussion transcript."""

    speaker: str
    role: str
    content: str
    phase: str  # "board_turn", "synthesis", "moderator"
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

    max_turns: int = 30
    moderator_temperature: float = MODERATOR_TEMPERATURE

    def __init__(
        self,
        max_turns: int = 30,
        moderator_temperature: float = MODERATOR_TEMPERATURE,
        *,
        max_rounds: int | None = None,
        spiral_check_interval: int = 3,
    ) -> None:
        # Accept max_rounds as a legacy alias for max_turns
        self.max_turns = max_rounds if max_rounds is not None else max_turns
        self.moderator_temperature = moderator_temperature


@dataclass
class DeliberationResult:
    """Output of a completed discussion."""

    transcript: list[TranscriptEntry]
    summary: str
    board: Board | None = None
    mode_selection: str | None = None       # pre-exec only
    verdict: str | None = None              # post-exec only ("accept" | "revise")
    revision_guidance: str | None = None    # when verdict == "revise"
    total_input_tokens: int = 0
    total_output_tokens: int = 0


# ── Prompt builders ───────────────────────────────────────────


def _board_turn_prompt(
    agent_role: str,
    board: Board,
    roster: list[str],
    task: str,
    is_reflecting: bool,
    prior_output: str | None,
    turn_number: int,
) -> str:
    """Build the prompt an agent sees on their turn."""
    board_text = board.render(roster)

    parts: list[str] = []

    if is_reflecting and prior_output:
        parts.append(
            f"**Task:** {task}\n\n"
            f"**Team output to review:**\n{prior_output[:3000]}\n\n"
            "The team is reflecting on the quality of this output."
        )
    else:
        parts.append(f"**Task:** {task}")

    parts.append(f"\n**Current Board (turn {turn_number}):**\n{board_text}")

    parts.append(
        f"\nYou are **{agent_role}**. Review the board and respond with "
        "structured actions:\n"
        "- **new_points**: Raise new claims the board hasn't covered.\n"
        "- **reactions**: React to existing points by ID "
        "(agree/disagree/question + reasoning).\n"
        "- **amendments**: Propose revised wording for a point by ID "
        "(new_claim + reason). This resets all approvals on that point.\n"
        "- **done**: Set to true if you have nothing to add, react to, "
        "or amend.\n\n"
        "Be concise. One sentence per reasoning. Focus on substance."
    )

    return "\n".join(parts)


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


# ── Transcript / format helpers (backward compat) ─────────────


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
    return content.strip().upper() == "PASS"


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
    allowed_modes: list[str] | None = None,
) -> DeliberationResult:
    """Run the board-based deliberation protocol.

    Round-robin: each agent takes a turn reading the board and responding
    with structured actions (raise / react / amend / done).

    Convergence: all agents declare ``done`` in consecutive turns AND
    no points remain in ``open`` status.  Contested points do NOT block
    convergence -- they become open items for the moderator to flag.

    Single-agent shortcut: one agent raises points, then straight to synthesis.
    """
    board = Board()
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

    # Pre-build response formats
    turn_format = json_schema_format(
        "BoardTurnResponse", BoardTurnResponse.model_json_schema(),
    )
    synth_format = json_schema_format(
        "DiscussionSynthesis", DiscussionSynthesis.model_json_schema(),
    )
    reflect_format = json_schema_format(
        "ReflectionSynthesis", ReflectionSynthesis.model_json_schema(),
    )

    # ── Single agent shortcut ─────────────────────────────────
    if len(agents) == 1:
        agent = agents[0]
        if is_reflecting:
            opening = _opening_prompt_reflect(task, prior_output)  # type: ignore[arg-type]
        else:
            opening = _opening_prompt_think(task)

        resp = await agent.run(
            [Message(role="user", content=opening)],
            run_context=run_context,
        )
        total_in += resp.input_tokens
        total_out += resp.output_tokens

        # Record the agent's perspective as a point on the board
        board.add_point(claim=resp.content, author=agent.role)

        transcript.append(TranscriptEntry(
            speaker=agent.role, role=agent.role,
            content=resp.content, phase="board_turn",
        ))
        if event_bus:
            await event_bus.emit(Event(
                type=EventType.AGENT_MESSAGE,
                data={"agent": agent.role, "content": resp.content, "phase": phase_label},
                project_id=project_id,
            ))
            await event_bus.emit(Event(
                type=EventType.DELIBERATION_CYCLE,
                data={"round": 1, "converged": True, "speakers": 1, "phase": phase_label},
                project_id=project_id,
            ))

    else:
        # ── Multi-agent round-robin ───────────────────────────
        done_agents: set[str] = set()
        turn_number = 0

        for turn_number in range(1, config.max_turns + 1):
            if run_context:
                await run_context.check_pause()

            # Pick the next agent (round-robin)
            agent = agents[(turn_number - 1) % len(agents)]

            prompt = _board_turn_prompt(
                agent_role=agent.role,
                board=board,
                roster=roster,
                task=task,
                is_reflecting=is_reflecting,
                prior_output=prior_output,
                turn_number=turn_number,
            )

            resp = await agent.run(
                [Message(role="user", content=prompt)],
                response_format=turn_format,
                run_context=run_context,
            )
            total_in += resp.input_tokens
            total_out += resp.output_tokens

            turn_data = parse_llm_json(resp.content, BoardTurnResponse)

            # Apply actions to the board
            actions_taken: list[str] = []

            for new_pt in turn_data.new_points:
                pt = board.add_point(claim=new_pt.claim, author=agent.role)
                actions_taken.append(f"raised point {pt.id}: \"{new_pt.claim}\"")
                # New points invalidate done status for other agents
                done_agents.discard(agent.role)
                for other in roster:
                    if other != agent.role:
                        done_agents.discard(other)

            for rxn in turn_data.reactions:
                point = board.get_point(rxn.point_id)
                if point:
                    stance = Stance(rxn.stance)
                    point.react(agent.role, stance, rxn.reasoning)
                    actions_taken.append(
                        f"{rxn.stance} point {rxn.point_id}: \"{rxn.reasoning}\""
                    )
                    if stance == Stance.DISAGREE:
                        for other in roster:
                            if other != agent.role:
                                done_agents.discard(other)

            for amd in turn_data.amendments:
                point = board.get_point(amd.point_id)
                if point:
                    point.amend(amd.new_claim, amended_by=agent.role, reason=amd.reason)
                    actions_taken.append(
                        f"amended point {amd.point_id} to: \"{amd.new_claim}\""
                    )
                    # Amendment invalidates everyone's done status
                    done_agents.clear()

            if turn_data.done and not actions_taken:
                done_agents.add(agent.role)

            # Transcript
            summary = "; ".join(actions_taken) if actions_taken else "done"
            transcript.append(TranscriptEntry(
                speaker=agent.role, role=agent.role,
                content=summary, phase="board_turn",
            ))

            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.AGENT_MESSAGE,
                    data={
                        "agent": agent.role,
                        "content": summary,
                        "phase": phase_label,
                        "actions": len(actions_taken),
                    },
                    project_id=project_id,
                ))

            # Check convergence
            all_done = done_agents >= set(roster)
            settled = board.is_settled(roster)

            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.DELIBERATION_CYCLE,
                    data={
                        "round": turn_number,
                        "converged": all_done and settled,
                        "speakers": 1,
                        "phase": phase_label,
                        "done_agents": len(done_agents),
                        "total_agents": len(roster),
                        "board_settled": settled,
                    },
                    project_id=project_id,
                ))

            if all_done and settled:
                logger.info(
                    "Board converged -- all agents done, all points settled "
                    "(turn %d)", turn_number,
                )
                break

            # Contested points don't block -- if everyone is done, wrap up
            if all_done and not settled:
                logger.info(
                    "All agents done but %d contested points remain -- "
                    "proceeding to synthesis (turn %d)",
                    sum(
                        1 for s in board.all_status(roster).values()
                        if s == PointStatus.CONTESTED
                    ),
                    turn_number,
                )
                break

        else:
            logger.info(
                "Deliberation hit max turns (%d) -- proceeding to synthesis",
                config.max_turns,
            )

    # ── SYNTHESIZE ────────────────────────────────────────────
    board_text = board.render(roster, compact_consensus=False)
    synthesis_context = (
        f"Task: {task}\n\n"
        f"Context: {context}\n\n"
        f"Deliberation board:\n{board_text}"
    )

    if not is_reflecting:
        mode_constraint = ""
        if allowed_modes:
            mode_constraint = (
                f" You MUST select mode_selection from: {allowed_modes}. "
                "Do NOT pick a mode outside this list."
            )

        # Gather open items from contested points
        statuses = board.all_status(roster)
        contested_points = [
            p for p in board.points
            if statuses.get(p.id) == PointStatus.CONTESTED
        ]
        contested_note = ""
        if contested_points:
            items = ", ".join(
                f"point {p.id} (\"{p.current.claim}\")"
                for p in contested_points
            )
            contested_note = (
                f"\n\nNote: these points are contested (unresolved "
                f"disagreement): {items}. Include them as open_items."
            )

        synth_prompt = (
            f"{synthesis_context}\n\n"
            "Synthesise the board into a pre-execution summary. "
            "Identify the consensus points, any contested/open items, and "
            f"select the best interaction mode for execution."
            f"{mode_constraint}{contested_note}"
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
            board=board,
            mode_selection=synth.mode_selection,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
        )
    else:
        synth_prompt = (
            f"{synthesis_context}\n\n"
            f"The team produced this output:\n{prior_output[:3000]}\n\n"  # type: ignore[index]
            "Synthesise the team's reflection from the board. Should the "
            "output be accepted as-is, or does it need revision? If revision "
            "is needed, provide specific guidance on what to fix."
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
            board=board,
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
                "total_points": len(board.points),
                "consensus_points": sum(
                    1 for s in board.all_status(roster).values()
                    if s == PointStatus.CONSENSUS
                ),
                "contested_points": sum(
                    1 for s in board.all_status(roster).values()
                    if s == PointStatus.CONTESTED
                ),
            },
            project_id=project_id,
        ))

    return result


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
    """Run a board-based team discussion triggered by a user question.

    Thin wrapper around ``deliberate()`` -- the user's message becomes
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
