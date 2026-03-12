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
from typing import Any, Callable, Coroutine

from pydantic import ValidationError

from agentagent.config import CompanyConfig, WorkflowStep
from agentagent.core.agent import Agent, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.schemas import JSON_MODE, GateEvaluation, parse_llm_json
from agentagent.core.team import Team, TeamOutput
from agentagent.store.repository import Repository

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
    ) -> None:
        self._config = config
        self._teams = teams
        self._repo = repository
        self._event_bus = event_bus
        self._project_id = project_id
        self._escalation_handler = escalation_handler
        self._pause_event = pause_event
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

    async def run_workflow(self, user_prompt: str) -> WorkflowState:
        """Execute the full workflow pipeline.

        Runs steps in dependency order, executes parallel steps concurrently,
        evaluates gates, and handles failures.
        """
        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.WORKFLOW_STEP_START,
                data={"message": "Workflow started", "prompt": user_prompt[:200]},
                project_id=self._project_id,
            ))

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
        # Block here while paused
        if self._pause_event is not None:
            await self._pause_event.wait()

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
        )
        step_state.team_output = output
        self._state.total_input_tokens += output.total_input_tokens
        self._state.total_output_tokens += output.total_output_tokens

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

    def _build_task(self, step_name: str, user_prompt: str) -> str:
        """Build the task description including upstream context."""
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
