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
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from agentagent.core.events import RunContext

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
        run_context: "RunContext | None" = None,
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
        run_context: "RunContext | None" = None,
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
        run_context: "RunContext | None" = None,
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
        run_context: "RunContext | None" = None,
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

        # Phase 2: Execute subtasks in dependency-ordered layers
        agent_map = {a.role: a for a in agents}
        results: dict[str, str] = {}

        layers = _topological_layers(subtasks)

        async def execute_subtask(
            subtask: dict, dep_context: str,
        ) -> tuple[str, str]:
            assignee = subtask.get("assignee", agents[0].role)
            agent = agent_map.get(assignee, agents[0])
            subtask_desc = subtask.get("task", "")

            msg = [
                Message(
                    role="user",
                    content=(
                        f"Context:\n{context}\n\n"
                        f"{dep_context}"
                        f"Your assigned subtask:\n{subtask_desc}\n\n"
                        "Complete this subtask. Be thorough and produce complete, "
                        "working output. If you're writing code, make it production-ready."
                    ),
                )
            ]
            resp = await agent.run(msg, run_context=run_context)
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
            return subtask_desc, resp.content

        for layer in layers:
            # Interrupt check between layers
            if run_context:
                await run_context.check_pause()

            # Build dependency context from completed subtask results
            dep_context = ""
            for st in layer:
                deps = st.get("dependencies", [])
                dep_parts = [
                    f"Result of '{dep}':\n{results[dep]}\n"
                    for dep in deps if dep in results
                ]
                if dep_parts:
                    dep_context = (
                        "## Completed dependency outputs:\n"
                        + "\n".join(dep_parts) + "\n\n"
                    )

            layer_results = await asyncio.gather(
                *(execute_subtask(st, dep_context) for st in layer)
            )
            for desc, content in layer_results:
                results[desc] = content

        # Phase 3: Integration — drain agent signals and include them
        signal_lines: list[str] = []
        if run_context:
            while not run_context.agent_channel.empty():
                try:
                    sig = run_context.agent_channel.get_nowait()
                    signal_lines.append(
                        f"- [{sig.get('severity', 'info')}] {sig.get('message', '')}"
                    )
                except asyncio.QueueEmpty:
                    break

        results_text = "\n\n---\n\n".join(
            f"### {desc}:\n{content}" for desc, content in results.items()
        )

        signal_block = ""
        if signal_lines:
            signal_block = (
                "\n\n## Agent Signals (flagged during execution):\n"
                + "\n".join(signal_lines)
                + "\n\nResolve any conflicts or issues raised above.\n"
            )

        integrate_msg = [
            Message(
                role="user",
                content=(
                    f"Original task:\n{task}\n\n"
                    f"Subtask results:\n\n{results_text}\n"
                    f"{signal_block}\n"
                    "Integrate all subtask results into a cohesive final output. "
                    "Resolve any conflicts or inconsistencies. "
                    "Produce the complete, integrated result."
                ),
            )
        ]
        integrate_resp = await leader.run(integrate_msg, run_context=run_context)
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
        run_context: "RunContext | None" = None,
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


# ── Topological sort helper ──────────────────────────────────


def _topological_layers(subtasks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group subtasks into dependency layers using Kahn's algorithm.

    Subtasks within a layer have no inter-dependencies and can run in parallel.
    Layers execute sequentially.  If a cycle is detected the remaining subtasks
    are placed in a final catch-all layer.
    """
    task_descs = [s.get("task", "") for s in subtasks]
    desc_to_subtask = {s.get("task", ""): s for s in subtasks}
    desc_set = set(task_descs)

    # Build adjacency: dep → list of subtasks that depend on it
    in_degree: dict[str, int] = {d: 0 for d in task_descs}
    dependents: dict[str, list[str]] = defaultdict(list)

    for st in subtasks:
        desc = st.get("task", "")
        for dep in st.get("dependencies", []):
            if dep in desc_set:
                in_degree[desc] += 1
                dependents[dep].append(desc)

    # Kahn's BFS
    layers: list[list[dict[str, Any]]] = []
    queue: deque[str] = deque(d for d, deg in in_degree.items() if deg == 0)

    while queue:
        layer_descs = list(queue)
        queue.clear()
        layers.append([desc_to_subtask[d] for d in layer_descs])
        for d in layer_descs:
            for child in dependents[d]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    # Remaining nodes form a cycle — dump them in a final layer
    remaining = [
        desc_to_subtask[d] for d, deg in in_degree.items() if deg > 0
    ]
    if remaining:
        logger.warning("Subtask dependency cycle detected — running remaining subtasks together")
        layers.append(remaining)

    return layers if layers else [subtasks]


# Mode registry
MODE_MAP: dict[str, InteractionModeBase] = {
    "generative": GenerativeMode(),
    "evaluative": EvaluativeMode(),
    "execution": ExecutionMode(),
    "decision": DecisionMode(),
}
