"""Event system for streaming agent activity to the UI.

Also defines ``RunContext``, the shared context object threaded through
the entire execution chain (Forum → Team → Moderator → Mode → Agent).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    # Agent-level
    AGENT_MESSAGE = "agent_message"
    AGENT_TOOL_CALL = "agent_tool_call"
    # Team-level
    TEAM_ROUND_START = "team_round_start"
    TEAM_ROUND_END = "team_round_end"
    TEAM_MODE_SELECTED = "team_mode_selected"
    TEAM_TASK_ASSIGNED = "team_task_assigned"
    # Forum-level
    FORUM_HANDOFF = "forum_handoff"
    FORUM_GATE_RESULT = "forum_gate_result"
    FORUM_ESCALATION = "forum_escalation"
    # Knowledge store
    DECISION_MADE = "decision_made"
    DECISION_SUPERSEDED = "decision_superseded"
    ARTIFACT_CREATED = "artifact_created"
    QUESTION_RAISED = "question_raised"
    # Workflow
    WORKFLOW_STEP_START = "workflow_step_start"
    WORKFLOW_STEP_COMPLETE = "workflow_step_complete"
    WORKFLOW_COMPLETE = "workflow_complete"
    # User
    USER_INPUT_REQUESTED = "user_input_requested"
    USER_INPUT_RECEIVED = "user_input_received"
    # File
    FILE_WRITTEN = "file_written"
    # Cost
    COST_UPDATE = "cost_update"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    project_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "project_id": self.project_id,
        }


# Type alias for event handler
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async event bus for broadcasting events to subscribers.

    Keeps a per-project history so late-connecting WebSockets can replay
    events they missed.
    """

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._history: dict[str, list[dict[str, Any]]] = {}

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        try:
            self._handlers.remove(handler)
        except ValueError:
            pass

    def get_project_history(self, project_id: str) -> list[dict[str, Any]]:
        """Return all past events for a project (serialised dicts)."""
        return list(self._history.get(project_id, []))

    async def emit(self, event: Event) -> None:
        # Store for replay
        if event.project_id:
            self._history.setdefault(event.project_id, []).append(event.to_dict())

        for handler in self._handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception("Event handler error for %s", event.type)


@dataclass
class RunContext:
    """Shared context threaded through Forum → Team → Moderator → Mode → Agent.

    Bundles every cross-cutting concern so downstream code never needs to
    accept a growing list of individual parameters.
    """

    project_id: str
    event_bus: EventBus
    pause_event: asyncio.Event
    message_queue: asyncio.Queue[dict[str, str]]
    agent_channel: asyncio.Queue[dict[str, str]]
    mode: str = "interactive"  # "interactive" or "autonomous"
    _cancel: bool = field(default=False, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def cancel(self) -> None:
        self._cancel = True

    async def check_pause(self) -> None:
        """Block while paused and raise if cancelled."""
        await self.pause_event.wait()
        if self._cancel:
            raise asyncio.CancelledError("RunContext cancelled")
