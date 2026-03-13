"""Forum + Program Manager — multi-team orchestration layer.

The forum is instantiated only when >1 team exists. The Program Manager
owns the workflow pipeline: dependency tracking, gate evaluation,
team sequencing, parallel execution, and user escalation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from pydantic import ValidationError

from agentagent.config import CompanyConfig, WorkflowStep
from agentagent.core.agent import Agent, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.schemas import JSON_MODE, ComplexityClassification, GateEvaluation, MessageClassification, parse_llm_json
from agentagent.core.team import Team, TeamOutput
from agentagent.store.repository import Repository

if TYPE_CHECKING:
    from agentagent.core.events import RunContext

logger = logging.getLogger(__name__)


class GateResult(str, Enum):
    APPROVED = "approved"
    APPROVED_WITH_NOTES = "approved_with_notes"
    RETURNED = "returned"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepState:
    """Tracks the state of a single workflow step."""

    step: WorkflowStep
    status: StepStatus = StepStatus.PENDING
    team_output: TeamOutput | None = None
    gate_result: GateResult | None = None
    gate_notes: str = ""
    attempts: int = 0


@dataclass
class WorkflowState:
    """Full workflow state across all steps."""

    steps: dict[str, StepState] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    is_complete: bool = False


# Type for user escalation callback
EscalationHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, str]]


class ProgramManager:
    """Manages the multi-team workflow pipeline.

    Responsibilities:
    - Track step dependencies and determine readiness
    - Execute teams in the correct order (with parallelism where configured)
    - Evaluate gates between steps
    - Handle on_fail loops
    - Escalate deadlocks to the user
    """

    def __init__(
        self,
        config: CompanyConfig,
        teams: dict[str, Team],
        repository: Repository,
        event_bus: EventBus | None = None,
        project_id: str = "",
        escalation_handler: EscalationHandler | None = None,
        pause_event: asyncio.Event | None = None,
        run_context: "RunContext | None" = None,
    ) -> None:
        self._config = config
        self._teams = teams
        self._repo = repository
        self._event_bus = event_bus
        self._project_id = project_id
        self._escalation_handler = escalation_handler
        self._pause_event = pause_event
        self._run_context = run_context
        self._state = WorkflowState()
        self._pm_agent = Agent(
            role="program_manager",
            persona=(
                "You are the Program Manager. You oversee the entire workflow, "
                "evaluate whether team outputs meet gate criteria, and decide "
                "whether work should proceed, be revised, or escalated to the user. "
                "Be rigorous but practical. Focus on whether the output actually "
                "addresses the requirements."
            ),
            model=config.default_model,
        )

        # Initialize step states
        for ws in config.workflow:
            self._state.steps[ws.step] = StepState(step=ws)

    @property
    def state(self) -> WorkflowState:
        return self._state

    @property
    def workflow_state(self) -> WorkflowState:
        """Alias for ``state`` used by the orchestrator."""
        return self._state

    def _is_step_ready(self, step_name: str) -> bool:
        """Check if all dependencies for a step have been completed and approved."""
        step_state = self._state.steps.get(step_name)
        if not step_state:
            return False
        if step_state.status != StepStatus.PENDING:
            return False

        for dep in step_state.step.depends_on:
            # dep is a gate name — find the step that produces this gate
            dep_step = next(
                (s for s in self._config.workflow if s.gate == dep), None
            )
            if not dep_step:
                return False
            dep_state = self._state.steps.get(dep_step.step)
            if not dep_state or dep_state.status != StepStatus.COMPLETED:
                return False

        return True

    def _get_ready_steps(self) -> list[str]:
        """Get all steps that are ready to execute (dependencies met)."""
        return [name for name in self._state.steps if self._is_step_ready(name)]

    # Steps that actually build the product — never skipped
    _EXECUTION_STEPS = frozenset({"engineering", "qa"})

    async def run_workflow(self, user_prompt: str, selected_steps: set[str] | None = None) -> WorkflowState:
        """Execute the full workflow pipeline.

        Runs steps in dependency order, executes parallel steps concurrently,
        evaluates gates, and handles failures.

        If ``selected_steps`` is provided, only those steps are executed;
        all others are auto-completed with the user prompt as context.
        When ``selected_steps`` is ``None`` and the request is simple,
        planning steps are fast-tracked automatically.
        """
        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.WORKFLOW_STEP_START,
                data={"message": "Workflow started", "prompt": user_prompt[:200]},
                project_id=self._project_id,
            ))

        # ── Decide which steps to skip ──
        if selected_steps is not None:
            # Skip everything NOT in the user's selection
            excluded = {name for name in self._state.steps if name not in selected_steps}
            if excluded:
                await self._skip_steps(excluded, user_prompt)
        elif await self._is_simple_request(user_prompt):
            # Fast-track: skip planning steps for simple requests
            excluded = {name for name in self._state.steps if name not in self._EXECUTION_STEPS}
            if excluded:
                await self._skip_steps(excluded, user_prompt)

        max_iterations = len(self._config.workflow) * 3  # Allow for retries

        for _ in range(max_iterations):
            ready = self._get_ready_steps()
            if not ready:
                # Check if we're done or stuck
                all_complete = all(
                    s.status == StepStatus.COMPLETED for s in self._state.steps.values()
                )
                if all_complete:
                    self._state.is_complete = True
                    break

                any_in_progress = any(
                    s.status == StepStatus.IN_PROGRESS for s in self._state.steps.values()
                )
                if not any_in_progress:
                    # Stuck — no ready steps and nothing in progress
                    logger.error("Workflow stuck — no ready steps")
                    if self._escalation_handler:
                        await self._escalation_handler(
                            "Workflow is stuck. No steps can proceed.",
                            {"state": {k: v.status for k, v in self._state.steps.items()}},
                        )
                    break
                continue

            # Group parallel steps
            parallel_groups = self._group_parallel_steps(ready)

            for group in parallel_groups:
                if len(group) == 1:
                    await self._execute_step(group[0], user_prompt)
                else:
                    # Execute parallel steps concurrently
                    await asyncio.gather(
                        *(self._execute_step(s, user_prompt) for s in group)
                    )

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.WORKFLOW_COMPLETE,
                data={
                    "total_input_tokens": self._state.total_input_tokens,
                    "total_output_tokens": self._state.total_output_tokens,
                },
                project_id=self._project_id,
            ))

        return self._state

    def _group_parallel_steps(self, ready: list[str]) -> list[list[str]]:
        """Group ready steps that can run in parallel."""
        groups: list[list[str]] = []
        used: set[str] = set()

        for step_name in ready:
            if step_name in used:
                continue
            step_state = self._state.steps[step_name]
            parallel = step_state.step.parallel_with
            group = [step_name]
            for p in parallel:
                if p in ready and p not in used:
                    group.append(p)
                    used.add(p)
            used.add(step_name)
            groups.append(group)

        return groups

    async def _execute_step(self, step_name: str, user_prompt: str) -> None:
        """Execute a single workflow step: run team → evaluate gate."""
        # Block here while paused (prefer RunContext, fall back to raw event)
        if self._run_context:
            await self._run_context.check_pause()
        elif self._pause_event is not None:
            await self._pause_event.wait()

        # Check for pending user messages
        await self._check_for_messages(step_name)

        step_state = self._state.steps[step_name]
        step_state.status = StepStatus.IN_PROGRESS
        step_state.attempts += 1

        team = self._teams.get(step_name)
        if not team:
            logger.error("No team found for step: %s", step_name)
            step_state.status = StepStatus.FAILED
            return

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.WORKFLOW_STEP_START,
                data={
                    "step": step_name,
                    "gate": step_state.step.gate,
                    "attempt": step_state.attempts,
                },
                project_id=self._project_id,
            ))

        # Build task from user prompt + upstream context
        task = self._build_task(step_name, user_prompt)

        # Run the team
        output = await team.execute_task(
            task=task,
            output_artifact_types=step_state.step.output,
            gate_criteria=step_state.step.gate_criteria.model_dump() if step_state.step.gate_criteria else None,
            run_context=self._run_context,
        )
        step_state.team_output = output
        self._state.total_input_tokens += output.total_input_tokens
        self._state.total_output_tokens += output.total_output_tokens

        # Post-execution file scan for execution steps
        if step_name in self._EXECUTION_STEPS and self._run_context:
            await self._scan_workspace_files()

        # Evaluate gate
        gate_result, gate_notes = await self._evaluate_gate(step_state, output)
        step_state.gate_result = gate_result
        step_state.gate_notes = gate_notes

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.FORUM_GATE_RESULT,
                data={
                    "step": step_name,
                    "gate": step_state.step.gate,
                    "result": gate_result.value,
                    "notes": gate_notes,
                    "confidence": output.confidence,
                },
                project_id=self._project_id,
            ))

        if gate_result in (GateResult.APPROVED, GateResult.APPROVED_WITH_NOTES):
            step_state.status = StepStatus.COMPLETED
            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.WORKFLOW_STEP_COMPLETE,
                    data={"step": step_name, "gate": step_state.step.gate},
                    project_id=self._project_id,
                ))
        else:
            # Gate failed — retry up to 3 times
            if step_state.attempts < 3:
                # If on_fail points to another step, reset that; otherwise retry self
                fail_target = step_state.step.on_fail or step_name
                if fail_target in self._state.steps:
                    self._state.steps[fail_target].status = StepStatus.PENDING
                step_state.status = StepStatus.PENDING
                logger.info(
                    "Gate %s returned, looping back to %s (attempt %d)",
                    step_state.step.gate, fail_target, step_state.attempts,
                )
            else:
                # Max retries exceeded — escalate
                logger.warning(
                    "Gate %s failed after %d attempts, marking step %s as failed",
                    step_state.step.gate, step_state.attempts, step_name,
                )
                if self._escalation_handler:
                    await self._escalation_handler(
                        f"Gate '{step_state.step.gate}' failed after {step_state.attempts} attempts.",
                        {"step": step_name, "notes": gate_notes},
                    )
                step_state.status = StepStatus.FAILED

    # ── Fast-track helpers ──────────────────────────────────────

    async def _is_simple_request(self, prompt: str) -> bool:
        """Ask the PM agent whether this request is simple enough to skip planning.

        Returns True if the LLM judges the request as simple/trivial.
        Falls back to False (full pipeline) on any error.
        """
        messages = [
            Message(
                role="user",
                content=(
                    "You are a project complexity classifier. Given the following "
                    "project request, decide whether it is SIMPLE or COMPLEX.\n\n"
                    "SIMPLE = can be built in a single sitting with no meaningful "
                    "design, architecture, or product planning needed. Examples: "
                    "hello world, calculator, to-do list, counter app, static page.\n\n"
                    "COMPLEX = needs real planning, design decisions, multiple "
                    "components, APIs, authentication, data modelling, etc.\n\n"
                    f"Request: {prompt}\n\n"
                    'Respond with ONLY this JSON: {"complexity": "simple"} or {"complexity": "complex"}'
                ),
            )
        ]
        try:
            resp = await self._pm_agent.run(messages, response_format=JSON_MODE)
            result = parse_llm_json(resp.content, ComplexityClassification)
            return result.complexity == "simple"
        except Exception:
            logger.warning("Complexity classification failed, using full pipeline")
            return False

    async def _skip_steps(self, excluded: set[str], user_prompt: str) -> None:
        """Auto-complete the given steps with a brief stub.

        Marks each excluded step as COMPLETED with a minimal TeamOutput so
        that dependency checks pass.
        """
        logger.info("Skipping steps: %s", excluded)

        stub_content = (
            f"Step auto-completed.\n\n"
            f"Request: {user_prompt}\n\n"
            f"Build exactly what was asked for, nothing more. "
            f"Keep it minimal and straightforward."
        )

        for step_name in excluded:
            step_state = self._state.steps.get(step_name)
            if not step_state:
                continue
            step_state.status = StepStatus.COMPLETED
            step_state.gate_result = GateResult.APPROVED
            step_state.gate_notes = "Skipped"
            step_state.team_output = TeamOutput(
                content=stub_content,
                confidence=1.0,
                rounds_used=0,
            )

            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.WORKFLOW_STEP_START,
                    data={
                        "step": step_name,
                        "gate": step_state.step.gate,
                        "attempt": 0,
                    },
                    project_id=self._project_id,
                ))
                await self._event_bus.emit(Event(
                    type=EventType.WORKFLOW_STEP_COMPLETE,
                    data={
                        "step": step_name,
                        "gate": step_state.step.gate,
                        "skipped": True,
                    },
                    project_id=self._project_id,
                ))

    async def _fast_track_planning(self, user_prompt: str) -> None:
        """Auto-complete all planning steps with brief stubs.

        Marks every non-execution step as COMPLETED with a minimal
        TeamOutput so that dependency checks pass and the workflow
        jumps straight to engineering / qa.
        """
        logger.info("Fast-tracking planning steps for simple request")

        stub_content = (
            f"Simple project — fast-tracked.\n\n"
            f"Request: {user_prompt}\n\n"
            f"Build exactly what was asked for, nothing more. "
            f"Keep it minimal and straightforward."
        )

        for step_name, step_state in self._state.steps.items():
            if step_name in self._EXECUTION_STEPS:
                continue
            # Auto-complete with stub
            step_state.status = StepStatus.COMPLETED
            step_state.gate_result = GateResult.APPROVED
            step_state.gate_notes = "Fast-tracked (simple request)"
            step_state.team_output = TeamOutput(
                content=stub_content,
                confidence=1.0,
                rounds_used=0,
            )

            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.WORKFLOW_STEP_START,
                    data={
                        "step": step_name,
                        "gate": step_state.step.gate,
                        "attempt": 0,
                    },
                    project_id=self._project_id,
                ))
                await self._event_bus.emit(Event(
                    type=EventType.WORKFLOW_STEP_COMPLETE,
                    data={
                        "step": step_name,
                        "gate": step_state.step.gate,
                        "fast_tracked": True,
                    },
                    project_id=self._project_id,
                ))

    def _build_task(self, step_name: str, user_prompt: str) -> str:
        """Build the task description including upstream context and gate feedback."""
        step_state = self._state.steps[step_name]
        parts = [f"User's original request: {user_prompt}"]

        parts.append(
            "IMPORTANT: Match the scope and complexity of your output to the "
            "request. A simple request (e.g. 'hello world app', 'to-do list') "
            "should produce a proportionally simple, minimal output — not an "
            "enterprise-grade plan. Do NOT over-engineer. If it's a simple app, "
            "keep the vision short, the PRD minimal, the architecture trivial, "
            "and the implementation straightforward. Only scale up complexity "
            "when the request genuinely warrants it."
        )

        # Inject gate feedback from prior attempt
        if step_state.gate_result == GateResult.RETURNED and step_state.gate_notes:
            parts.append(
                f"\n## REVISION REQUIRED — Gate Feedback (attempt {step_state.attempts})\n"
                f"Your previous output was returned by the gate reviewer. "
                f"Address the following feedback:\n\n{step_state.gate_notes}"
            )

        # Add upstream outputs
        for dep_gate in step_state.step.depends_on:
            dep_step = next(
                (s for s in self._config.workflow if s.gate == dep_gate), None
            )
            if dep_step:
                dep_state = self._state.steps.get(dep_step.step)
                if dep_state and dep_state.team_output:
                    parts.append(
                        f"\n## Output from {dep_step.step} team:\n"
                        f"{dep_state.team_output.content[:3000]}"
                    )

        parts.append(f"\n## Your team's purpose: {step_state.step.step}")
        parts.append(f"Produce: {', '.join(step_state.step.output)}")

        # Execution-specific guidance: instruct agents to write actual files
        if step_name in self._EXECUTION_STEPS:
            parts.append(
                "\n## File Output Guidance\n"
                "You MUST write actual source code files using the file_system tool. "
                "Do NOT just describe code in conversation — write it to files. "
                "Organise files in a sensible directory structure. "
                "Each file should be complete and self-contained. "
                "After writing, verify by listing the directory."
            )

        return "\n\n".join(parts)

    async def _evaluate_gate(
        self, step_state: StepState, output: TeamOutput
    ) -> tuple[GateResult, str]:
        """Evaluate whether team output passes the gate criteria."""
        criteria = step_state.step.gate_criteria

        messages = [
            Message(
                role="user",
                content=(
                    f"Evaluate this team output for gate '{step_state.step.gate}'.\n\n"
                    f"Gate criteria: {criteria.description}\n"
                    f"Automated checks required: {criteria.automated_checks}\n\n"
                    f"Team output:\n{output.content[:4000]}\n\n"
                    "Evaluate thoroughly. Output JSON:\n"
                    '{"result": "approved|approved_with_notes|returned", '
                    '"notes": "specific feedback", '
                    '"missing": ["what is missing or needs improvement"]}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]

        resp = await self._pm_agent.run(messages, response_format=JSON_MODE)
        try:
            data = parse_llm_json(resp.content, GateEvaluation)
            logger.info(
                "Gate %s evaluation: %s — %s",
                step_state.step.gate, data.result, data.notes[:200],
            )
            return GateResult(data.result), data.notes
        except (ValidationError, ValueError):
            logger.warning(
                "Could not parse gate evaluation for %s, auto-approving: %s",
                step_state.step.gate, resp.content[:200],
            )
            # If we can't parse, approve with notes
            return GateResult.APPROVED_WITH_NOTES, resp.content

    # ── User message processing ─────────────────────────────────

    async def _check_for_messages(self, current_step: str) -> None:
        """Drain the message queue and process any pending user messages.

        Uses a lightweight PM agent call to classify the audience/action,
        then acts accordingly.
        """
        if not self._run_context:
            return

        queue = self._run_context.message_queue
        messages: list[dict[str, str]] = []
        while not queue.empty():
            try:
                messages.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        for msg in messages:
            action = msg.get("action", "message")

            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.USER_INPUT_RECEIVED,
                    data={"action": action, "message": msg.get("message", ""), "step": current_step},
                    project_id=self._project_id,
                ))

            if action == "veto":
                step_state = self._state.steps.get(current_step)
                if step_state and step_state.status == StepStatus.IN_PROGRESS:
                    step_state.status = StepStatus.PENDING
                    step_state.gate_result = GateResult.RETURNED
                    step_state.gate_notes = f"User vetoed: {msg.get('message', '')}"
                    logger.info("User vetoed step %s", current_step)

            elif action == "skip":
                step_state = self._state.steps.get(current_step)
                if step_state:
                    step_state.status = StepStatus.COMPLETED
                    step_state.gate_result = GateResult.APPROVED_WITH_NOTES
                    step_state.gate_notes = f"User skipped: {msg.get('message', '')}"
                    step_state.team_output = TeamOutput(
                        content=f"Step skipped by user: {msg.get('message', '')}",
                        confidence=1.0,
                        rounds_used=0,
                    )
                    logger.info("User skipped step %s", current_step)

            elif action == "constrain":
                # Inject constraint — store it so _build_task picks it up
                self._state.steps[current_step].gate_notes += (
                    f"\nUser constraint: {msg.get('message', '')}"
                )

            elif action == "converse":
                await self._handle_converse(msg, current_step)

            elif action == "end_conversation":
                await self._handle_end_conversation(msg, current_step)

            else:
                # Classify audience of freeform messages
                await self._route_user_message(msg, current_step)

    async def _route_user_message(
        self, msg: dict[str, str], current_step: str
    ) -> None:
        """Classify and route a freeform user message to the right scope."""
        step_names = list(self._state.steps.keys())
        classify_msg = [
            Message(
                role="user",
                content=(
                    f"A user sent this message during step '{current_step}':\n"
                    f"\"{msg.get('message', '')}\"\n\n"
                    f"Available steps: {step_names}\n\n"
                    "Classify the audience:\n"
                    "- \"current_step\" if the message is feedback/context for the current team\n"
                    "- \"workflow\" if it changes the overall direction or requirements\n\n"
                    'Respond with JSON: {{"audience": "current_step"|"workflow", '
                    '"summary": "one-line summary"}}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]
        try:
            resp = await self._pm_agent.run(classify_msg, response_format=JSON_MODE)
            result = parse_llm_json(resp.content, MessageClassification)
            if result.audience == "workflow":
                # Inject as constraint across all pending steps
                for name, step_state in self._state.steps.items():
                    if step_state.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                        step_state.gate_notes += f"\nUser message: {msg.get('message', '')}"
            # For current_step, the message is appended as gate_notes for context
            self._state.steps[current_step].gate_notes += (
                f"\nUser input: {msg.get('message', '')}"
            )
        except (ValidationError, ValueError):
            # Fallback: treat as current-step context
            self._state.steps[current_step].gate_notes += (
                f"\nUser input: {msg.get('message', '')}"
            )

    # ── Conversation handling ──────────────────────────────────────

    async def _handle_converse(self, msg: dict[str, str], current_step: str) -> None:
        """Handle a targeted conversation request.

        Routes to PM, team, or individual agent based on ``target``.
        The conversation result is injected back into the step context.
        """
        from agentagent.core.deliberation import DeliberationConfig, converse_with_team

        target = msg.get("target", "pm")
        user_message = msg.get("message", "")

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.CONVERSATION_START,
                data={"target": target, "step": current_step},
                project_id=self._project_id,
            ))

        if target == "pm":
            # Direct chat with PM
            resp = await self._pm_agent.run(
                [Message(role="user", content=user_message)],
                run_context=self._run_context,
            )
            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.CONVERSATION_MESSAGE,
                    data={"speaker": "program_manager", "content": resp.content, "target": target},
                    project_id=self._project_id,
                ))
            self._state.steps[current_step].gate_notes += (
                f"\nConversation with PM: {resp.content[:500]}"
            )

        elif target.startswith("team:"):
            team_name = target.split(":", 1)[1]
            team = self._teams.get(team_name)
            if not team:
                logger.warning("Team %s not found for conversation", team_name)
                return

            context = self._build_task(current_step, user_message)
            config = DeliberationConfig(max_rounds=4)
            result = await converse_with_team(
                moderator_agent=team.moderator_agent._agent,
                agents=team.experts,
                user_message=user_message,
                context=context,
                historian=team.historian,
                config=config,
                event_bus=self._event_bus,
                project_id=self._project_id,
                run_context=self._run_context,
            )
            self._state.steps[current_step].gate_notes += (
                f"\nTeam conversation summary: {result.summary[:500]}"
            )

        elif target.startswith("agent:"):
            # agent:{team}:{role}
            parts = target.split(":", 2)
            if len(parts) < 3:
                logger.warning("Invalid agent target format: %s", target)
                return
            team_name, agent_role = parts[1], parts[2]
            team = self._teams.get(team_name)
            if not team:
                logger.warning("Team %s not found for agent conversation", team_name)
                return

            agent = next((a for a in team.experts if a.role == agent_role), None)
            if not agent:
                logger.warning("Agent %s not found in team %s", agent_role, team_name)
                return

            resp = await agent.run(
                [Message(role="user", content=user_message)],
                run_context=self._run_context,
            )
            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.CONVERSATION_MESSAGE,
                    data={"speaker": agent_role, "content": resp.content, "target": target},
                    project_id=self._project_id,
                ))
            self._state.steps[current_step].gate_notes += (
                f"\nConversation with {agent_role}: {resp.content[:500]}"
            )

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.CONVERSATION_END,
                data={"target": target, "step": current_step},
                project_id=self._project_id,
            ))

    async def _handle_end_conversation(self, msg: dict[str, str], current_step: str) -> None:
        """End a conversation session and inject summary into context."""
        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.CONVERSATION_END,
                data={"step": current_step, "message": msg.get("message", "")},
                project_id=self._project_id,
            ))

    # ── File scanning ────────────────────────────────────────────

    async def _scan_workspace_files(self) -> None:
        """Scan the project workspace and emit ARTIFACT_CREATED events."""
        if not self._run_context:
            return
        work_dir = Path(f"workspace/{self._run_context.project_id}")
        if not work_dir.exists():
            return
        for path in sorted(work_dir.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(work_dir))
                await self._run_context.event_bus.emit(Event(
                    type=EventType.ARTIFACT_CREATED,
                    data={
                        "path": rel,
                        "size": path.stat().st_size,
                        "source": "file_scan",
                    },
                    project_id=self._run_context.project_id,
                ))
