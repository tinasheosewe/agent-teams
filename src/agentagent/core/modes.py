"""Interaction modes — the four protocols teams use to work.

Each mode implements a different collaboration pattern:
- Generative: create options from nothing, score, converge
- Evaluative: review an artifact against criteria
- Execution: divide work, build in parallel, integrate
- Decision: choose between options with tradeoffs
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agentagent.core.agent import Agent, AgentResponse, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.schemas import (
    JSON_MODE,
    OptionsResponse,
    ReviewResponse,
    ScoringResponse,
    TaskDecomposition,
    parse_llm_json,
)

logger = logging.getLogger(__name__)


@dataclass
class ModeResult:
    """Output of an interaction mode."""

    content: str
    decisions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.8
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)


class InteractionModeBase(ABC):
    """Base class for interaction modes."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Mode name for logging and config."""

    @abstractmethod
    async def execute(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None = None,
        project_id: str = "",
    ) -> ModeResult:
        """Run the mode protocol with the given agents and task."""


class GenerativeMode(InteractionModeBase):
    """Each agent independently proposes → pool → score → converge.

    1. Each agent generates a proposal independently
    2. All proposals are pooled and presented
    3. Each agent scores all proposals against the task criteria
    4. Highest-scoring proposal wins, with synthesis from runners-up
    """

    @property
    def name(self) -> str:
        return "generative"

    async def execute(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None = None,
        project_id: str = "",
    ) -> ModeResult:
        total_in = 0
        total_out = 0

        # Phase 1: Independent proposals (parallel)
        propose_msg = [
            Message(
                role="user",
                content=(
                    f"Context:\n{context}\n\n"
                    f"Task:\n{task}\n\n"
                    "Generate a detailed proposal for how to approach this task. "
                    "Be specific and concrete. Include your reasoning."
                ),
            )
        ]

        all_tool_calls: list[dict[str, Any]] = []
        proposals: list[tuple[Agent, str]] = []
        coros = [agent.run(propose_msg) for agent in agents]
        responses = await asyncio.gather(*coros)

        for agent, resp in zip(agents, responses):
            proposals.append((agent, resp.content))
            total_in += resp.input_tokens
            total_out += resp.output_tokens
            all_tool_calls.extend(resp.tool_calls_made)
            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.AGENT_MESSAGE,
                    data={"agent": agent.role, "content": resp.content, "phase": "proposal"},
                    project_id=project_id,
                ))

        # Phase 2: Scoring (each agent scores all proposals)
        proposals_text = "\n\n---\n\n".join(
            f"### Proposal by {agent.role}:\n{content}"
            for agent, content in proposals
        )
        score_msg = [
            Message(
                role="user",
                content=(
                    f"Task:\n{task}\n\n"
                    f"Here are all proposals:\n\n{proposals_text}\n\n"
                    "Score each proposal from 0-10 based on:\n"
                    "- Relevance to the task\n"
                    "- Completeness\n"
                    "- Feasibility\n"
                    "- Quality of reasoning\n\n"
                    "Output JSON: {\"scores\": [{\"agent\": \"role\", \"score\": N, \"reasoning\": \"why\"}]}\n"
                    "Return ONLY the JSON."
                ),
            )
        ]

        all_scores: dict[str, list[int]] = {}
        score_coros = [agent.run(score_msg, response_format=JSON_MODE) for agent in agents]
        score_responses = await asyncio.gather(*score_coros)

        for resp in score_responses:
            total_in += resp.input_tokens
            total_out += resp.output_tokens
            try:
                data = parse_llm_json(resp.content, ScoringResponse)
                for s in data.scores:
                    all_scores.setdefault(s.agent, []).append(s.score)
            except (ValidationError, ValueError):
                logger.warning("Failed to parse scoring output")

        # Phase 3: Synthesize winning proposal
        avg_scores = {
            role: sum(scores) / len(scores)
            for role, scores in all_scores.items()
            if scores
        }
        winner_role = max(avg_scores, key=avg_scores.get) if avg_scores else agents[0].role
        winner_proposal = next(
            (content for agent, content in proposals if agent.role == winner_role),
            proposals[0][1] if proposals else "",
        )

        # Ask the winner to synthesize with good ideas from other proposals
        synthesize_msg = [
            Message(
                role="user",
                content=(
                    f"Your proposal was selected as the best for this task:\n{task}\n\n"
                    f"Your proposal:\n{winner_proposal}\n\n"
                    f"Other proposals:\n{proposals_text}\n\n"
                    "Incorporate any good ideas from the other proposals into your approach. "
                    "Produce the final, refined version. Be specific and actionable."
                ),
            )
        ]
        winner_agent = next(
            (a for a in agents if a.role == winner_role), agents[0]
        )
        final_resp = await winner_agent.run(synthesize_msg)
        total_in += final_resp.input_tokens
        total_out += final_resp.output_tokens
        all_tool_calls.extend(final_resp.tool_calls_made)

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.AGENT_MESSAGE,
                data={
                    "agent": winner_agent.role,
                    "content": final_resp.content,
                    "phase": "synthesis",
                    "scores": avg_scores,
                },
                project_id=project_id,
            ))

        return ModeResult(
            content=final_resp.content,
            confidence=min(max(avg_scores.values()) / 10, 1.0) if avg_scores else 0.7,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            tool_calls_made=all_tool_calls,
        )


class EvaluativeMode(InteractionModeBase):
    """Review an artifact against criteria → surface issues → fix → agree.

    1. Each agent reviews the artifact independently
    2. Issues are pooled
    3. Fixes are proposed
    4. Agreement round
    """

    @property
    def name(self) -> str:
        return "evaluative"

    async def execute(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None = None,
        project_id: str = "",
    ) -> ModeResult:
        total_in = 0
        total_out = 0

        # Phase 1: Independent review (parallel)
        review_msg = [
            Message(
                role="user",
                content=(
                    f"Context:\n{context}\n\n"
                    f"Review task:\n{task}\n\n"
                    "Review the above thoroughly. Identify:\n"
                    "1. Issues, gaps, or risks\n"
                    "2. What's good and should be kept\n"
                    "3. Specific improvements with concrete suggestions\n\n"
                    "Be specific and constructive. Output JSON:\n"
                    '{"issues": [{"issue": "...", "severity": "critical|major|minor", '
                    '"suggestion": "..."}], "strengths": ["..."], '
                    '"overall_assessment": "pass|needs_changes|fail"}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]

        all_tool_calls: list[dict[str, Any]] = []
        all_issues: list[dict] = []
        all_strengths: list[str] = []
        assessments: list[str] = []

        coros = [agent.run(review_msg, response_format=JSON_MODE) for agent in agents]
        responses = await asyncio.gather(*coros)

        for agent, resp in zip(agents, responses):
            total_in += resp.input_tokens
            total_out += resp.output_tokens
            all_tool_calls.extend(resp.tool_calls_made)
            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.AGENT_MESSAGE,
                    data={"agent": agent.role, "content": resp.content, "phase": "review"},
                    project_id=project_id,
                ))
            try:
                data = parse_llm_json(resp.content, ReviewResponse)
                all_issues.extend(i.model_dump() for i in data.issues)
                all_strengths.extend(data.strengths)
                assessments.append(data.overall_assessment)
            except (ValidationError, ValueError):
                all_issues.append({"issue": resp.content, "severity": "major", "suggestion": ""})
                assessments.append("needs_changes")

        # Phase 2: Deduplicate and prioritize issues
        critical = [i for i in all_issues if i.get("severity") == "critical"]
        major = [i for i in all_issues if i.get("severity") == "major"]
        minor = [i for i in all_issues if i.get("severity") == "minor"]

        overall = "fail" if critical else ("needs_changes" if major else "pass")

        result_content = json.dumps({
            "overall_assessment": overall,
            "critical_issues": critical,
            "major_issues": major,
            "minor_issues": minor,
            "strengths": list(set(all_strengths)),
            "reviewer_assessments": assessments,
        }, indent=2)

        return ModeResult(
            content=result_content,
            confidence=0.9 if overall == "pass" else (0.5 if overall == "fail" else 0.7),
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            tool_calls_made=all_tool_calls,
        )


class ExecutionMode(InteractionModeBase):
    """Decompose → assign → build in parallel → integrate → verify.

    1. Leader agent decomposes the task into subtasks
    2. Subtasks are assigned to agents
    3. Agents execute in parallel
    4. Results are integrated
    """

    @property
    def name(self) -> str:
        return "execution"

    async def execute(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None = None,
        project_id: str = "",
    ) -> ModeResult:
        total_in = 0
        total_out = 0

        all_tool_calls: list[dict[str, Any]] = []

        if not agents:
            return ModeResult(content="No agents available for execution.")

        leader = agents[0]

        # Phase 1: Decompose task
        decompose_msg = [
            Message(
                role="user",
                content=(
                    f"Context:\n{context}\n\n"
                    f"Task to implement:\n{task}\n\n"
                    f"Available team members: {', '.join(a.role for a in agents)}\n\n"
                    "Break this task into concrete subtasks that can be worked on in parallel. "
                    "Assign each subtask to the most appropriate team member.\n\n"
                    'Output JSON: {"subtasks": [{"assignee": "role", "task": "specific task description", '
                    '"dependencies": ["other subtask descriptions if any"]}]}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]

        decompose_resp = await leader.run(decompose_msg, response_format=JSON_MODE)
        total_in += decompose_resp.input_tokens
        total_out += decompose_resp.output_tokens

        try:
            decomp = parse_llm_json(decompose_resp.content, TaskDecomposition)
            subtasks = [s.model_dump() for s in decomp.subtasks]
        except (ValidationError, ValueError):
            # Fallback: give the whole task to all agents
            subtasks = [{"assignee": a.role, "task": task} for a in agents]

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.TEAM_TASK_ASSIGNED,
                data={"subtasks": subtasks},
                project_id=project_id,
            ))

        # Phase 2: Execute subtasks (parallel where no dependencies)
        agent_map = {a.role: a for a in agents}
        results: dict[str, str] = {}

        # Simple approach: execute all subtasks in parallel
        # (dependency handling would add complexity; for MVP, we pass all context)
        async def execute_subtask(subtask: dict) -> tuple[str, str]:
            assignee = subtask.get("assignee", agents[0].role)
            agent = agent_map.get(assignee, agents[0])
            subtask_desc = subtask.get("task", "")

            msg = [
                Message(
                    role="user",
                    content=(
                        f"Context:\n{context}\n\n"
                        f"Your assigned subtask:\n{subtask_desc}\n\n"
                        "Complete this subtask. Be thorough and produce complete, "
                        "working output. If you're writing code, make it production-ready."
                    ),
                )
            ]
            resp = await agent.run(msg)
            all_tool_calls.extend(resp.tool_calls_made)
            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.AGENT_MESSAGE,
                    data={
                        "agent": agent.role,
                        "content": resp.content,
                        "phase": "execution",
                        "subtask": subtask_desc,
                    },
                    project_id=project_id,
                ))
            return assignee, resp.content

        subtask_results = await asyncio.gather(
            *(execute_subtask(st) for st in subtasks)
        )
        for assignee, content in subtask_results:
            results[assignee] = content

        # Phase 3: Integration
        results_text = "\n\n---\n\n".join(
            f"### {role}:\n{content}" for role, content in results.items()
        )

        integrate_msg = [
            Message(
                role="user",
                content=(
                    f"Original task:\n{task}\n\n"
                    f"Subtask results:\n\n{results_text}\n\n"
                    "Integrate all subtask results into a cohesive final output. "
                    "Resolve any conflicts or inconsistencies. "
                    "Produce the complete, integrated result."
                ),
            )
        ]
        integrate_resp = await leader.run(integrate_msg)
        total_in += integrate_resp.input_tokens
        total_out += integrate_resp.output_tokens
        all_tool_calls.extend(integrate_resp.tool_calls_made)

        return ModeResult(
            content=integrate_resp.content,
            artifacts=[{"type": "implementation", "content": r} for r in results.values()],
            confidence=0.75,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            tool_calls_made=all_tool_calls,
        )


class DecisionMode(InteractionModeBase):
    """Present options → tradeoffs → argue → vote → commit.

    1. Each agent proposes/evaluates options
    2. Tradeoffs are discussed
    3. Agents vote
    4. Decision is committed
    """

    @property
    def name(self) -> str:
        return "decision"

    async def execute(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None = None,
        project_id: str = "",
    ) -> ModeResult:
        total_in = 0
        total_out = 0

        # Phase 1: Each agent proposes options (parallel)
        options_msg = [
            Message(
                role="user",
                content=(
                    f"Context:\n{context}\n\n"
                    f"Decision needed:\n{task}\n\n"
                    "Propose concrete options for this decision. For each option:\n"
                    "- Name it clearly\n"
                    "- List pros and cons\n"
                    "- Identify risks\n"
                    "- State your recommendation and why\n\n"
                    'Output JSON: {"options": [{"name": "...", "pros": ["..."], '
                    '"cons": ["..."], "risks": ["..."]}], '
                    '"recommendation": "option name", "reasoning": "why"}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]

        all_tool_calls: list[dict[str, Any]] = []
        all_options: dict[str, dict] = {}
        recommendations: list[tuple[str, str, str]] = []  # (agent, option, reasoning)

        coros = [agent.run(options_msg, response_format=JSON_MODE) for agent in agents]
        responses = await asyncio.gather(*coros)

        for agent, resp in zip(agents, responses):
            total_in += resp.input_tokens
            total_out += resp.output_tokens
            all_tool_calls.extend(resp.tool_calls_made)
            if event_bus:
                await event_bus.emit(Event(
                    type=EventType.AGENT_MESSAGE,
                    data={"agent": agent.role, "content": resp.content, "phase": "options"},
                    project_id=project_id,
                ))
            try:
                data = parse_llm_json(resp.content, OptionsResponse)
                for opt in data.options:
                    if opt.name not in all_options:
                        all_options[opt.name] = opt.model_dump()
                    else:
                        # Merge pros/cons from multiple agents
                        all_options[opt.name]["pros"] = list(set(
                            all_options[opt.name].get("pros", []) + opt.pros
                        ))
                        all_options[opt.name]["cons"] = list(set(
                            all_options[opt.name].get("cons", []) + opt.cons
                        ))
                recommendations.append((agent.role, data.recommendation, data.reasoning))
            except (ValidationError, ValueError):
                recommendations.append((agent.role, "unclear", resp.content))

        # Phase 2: Vote — count recommendations
        vote_counts: dict[str, int] = {}
        for _, rec, _ in recommendations:
            vote_counts[rec] = vote_counts.get(rec, 0) + 1

        winner = max(vote_counts, key=vote_counts.get) if vote_counts else "no consensus"
        winner_details = all_options.get(winner, {})

        # Build decision record
        decision_data = {
            "topic": task[:200],
            "decision": winner,
            "rationale": "; ".join(
                f"{agent}: {reasoning}" for agent, rec, reasoning in recommendations if rec == winner
            ),
            "confidence": vote_counts.get(winner, 0) / len(agents) if agents else 0.5,
            "all_options": list(all_options.values()),
            "vote_breakdown": vote_counts,
        }

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.DECISION_MADE,
                data=decision_data,
                project_id=project_id,
            ))

        return ModeResult(
            content=json.dumps(decision_data, indent=2),
            decisions=[decision_data],
            confidence=decision_data["confidence"],
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            tool_calls_made=all_tool_calls,
        )


# Mode registry
MODE_MAP: dict[str, InteractionModeBase] = {
    "generative": GenerativeMode(),
    "evaluative": EvaluativeMode(),
    "execution": ExecutionMode(),
    "decision": DecisionMode(),
}
