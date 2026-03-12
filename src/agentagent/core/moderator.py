"""Moderator — selects interaction mode, manages turns, drives convergence.

The moderator follows rule-based decision trees where possible. Agents can
challenge the moderator's decisions; the moderator must justify or adjust.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from agentagent.config import InteractionMode
from agentagent.core.agent import Agent, Message
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.modes import MODE_MAP, ModeResult
from agentagent.core.schemas import (
    JSON_MODE,
    ChallengeResponse,
    CompletenessResponse,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

# Rule-based mode selection — maps task keywords to modes
MODE_RULES: list[tuple[list[str], str]] = [
    (["implement", "build", "code", "create files", "write code", "scaffold"], "execution"),
    (["review", "evaluate", "assess", "test", "check", "audit", "critique"], "evaluative"),
    (["choose", "decide", "select", "pick", "which", "vs", "versus"], "decision"),
    (["design", "propose", "brainstorm", "ideate", "explore", "define", "plan"], "generative"),
]


class Moderator:
    """Manages a team's workflow: mode selection, turn management, convergence.

    The moderator:
    1. Selects the interaction mode (rule-based, configurable)
    2. Runs the mode protocol
    3. Allows agents to challenge its decisions
    4. Monitors context usage and triggers compression
    """

    def __init__(
        self,
        model: str,
        preferred_modes: list[InteractionMode],
        max_rounds: int = 10,
        context_token_limit: int = 80_000,
    ) -> None:
        self._model = model
        self._preferred_modes = [m.value for m in preferred_modes]
        self._max_rounds = max_rounds
        self._context_token_limit = context_token_limit
        self._agent = Agent(
            role="moderator",
            persona=(
                "You are a team moderator. You manage team discussions, select "
                "interaction modes, decompose tasks, and drive convergence. "
                "You follow structured protocols. When challenged by team members, "
                "you must justify your decisions or adjust. You are decisive but "
                "fair. Keep discussions focused and productive."
            ),
            model=model,
        )

    def select_mode(self, task: str) -> str:
        """Select interaction mode using rule-based decision tree.

        Falls back to preferred modes from config, then to generative.
        """
        task_lower = task.lower()

        # Rule-based matching
        for keywords, mode in MODE_RULES:
            if any(kw in task_lower for kw in keywords):
                return mode

        # Fall back to first preferred mode
        if self._preferred_modes:
            return self._preferred_modes[0]

        return "generative"

    async def run_round(
        self,
        agents: list[Agent],
        task: str,
        context: str,
        event_bus: EventBus | None = None,
        project_id: str = "",
        forced_mode: str | None = None,
    ) -> ModeResult:
        """Execute a single round of team work.

        1. Select mode
        2. Present mode to agents for challenge
        3. Run the mode protocol
        4. Return results
        """
        # Step 1: Select mode
        mode_name = forced_mode or self.select_mode(task)

        if event_bus:
            await event_bus.emit(Event(
                type=EventType.TEAM_MODE_SELECTED,
                data={"mode": mode_name, "task": task[:200]},
                project_id=project_id,
            ))

        # Step 2: Challenge round — let agents object
        mode_name = await self._challenge_round(agents, mode_name, task, project_id, event_bus)

        # Step 3: Execute the mode
        mode = MODE_MAP.get(mode_name)
        if not mode:
            logger.error("Unknown mode: %s, falling back to generative", mode_name)
            mode = MODE_MAP["generative"]

        result = await mode.execute(
            agents=agents,
            task=task,
            context=context,
            event_bus=event_bus,
            project_id=project_id,
        )

        return result

    async def _challenge_round(
        self,
        agents: list[Agent],
        proposed_mode: str,
        task: str,
        project_id: str,
        event_bus: EventBus | None,
    ) -> str:
        """Give agents a chance to challenge the selected mode.

        Uses a lightweight single-turn check. If any agent objects with a
        good reason, the moderator considers and may adjust.
        """
        if len(agents) <= 1:
            return proposed_mode

        # Ask one representative agent (first in list) if they agree
        challenge_msg = [
            Message(
                role="user",
                content=(
                    f"The moderator has selected '{proposed_mode}' mode for this task:\n"
                    f"{task}\n\n"
                    "Do you agree this is the right approach? If not, briefly suggest "
                    "a better mode (generative, evaluative, execution, or decision) and why.\n\n"
                    'Output JSON: {"agree": true/false, "suggested_mode": "mode_name", '
                    '"reason": "brief explanation"}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]

        resp = await agents[0].run(challenge_msg, response_format=JSON_MODE)
        try:
            data = parse_llm_json(resp.content, ChallengeResponse)
            if not data.agree:
                suggested = data.suggested_mode or proposed_mode
                reason = data.reason
                if suggested in MODE_MAP:
                    logger.info(
                        "Agent %s challenged mode %s → %s: %s",
                        agents[0].role, proposed_mode, suggested, reason,
                    )
                    if event_bus:
                        await event_bus.emit(Event(
                            type=EventType.AGENT_MESSAGE,
                            data={
                                "agent": agents[0].role,
                                "content": f"Challenged mode {proposed_mode} → {suggested}: {reason}",
                                "phase": "challenge",
                            },
                            project_id=project_id,
                        ))
                    return suggested
        except (ValidationError, ValueError):
            pass

        return proposed_mode

    async def evaluate_completeness(
        self,
        task: str,
        result: ModeResult,
        gate_criteria: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Evaluate whether the round result satisfies the task.

        Returns (is_complete, reasoning).
        """
        criteria_text = ""
        if gate_criteria:
            criteria_text = f"\n\nAcceptance criteria:\n{json.dumps(gate_criteria, indent=2)}"

        messages = [
            Message(
                role="user",
                content=(
                    f"Task:\n{task}\n\n"
                    f"Result produced:\n{result.content[:3000]}\n"
                    f"{criteria_text}\n\n"
                    "Is this result complete and satisfactory for the task? "
                    'Output JSON: {"complete": true/false, "reasoning": "why", '
                    '"missing": ["what else is needed if incomplete"]}\n'
                    "Return ONLY the JSON."
                ),
            )
        ]

        resp = await self._agent.run(messages, response_format=JSON_MODE)
        try:
            data = parse_llm_json(resp.content, CompletenessResponse)
            return data.complete, data.reasoning
        except (ValidationError, ValueError):
            return False, resp.content

    def should_compress(self, estimated_tokens: int) -> bool:
        """Check if context is getting too large and needs compression."""
        return estimated_tokens > self._context_token_limit * 0.75
