"""Tests for the new architectural features:
- RunContext
- Topological sort
- File safety limits
- Signal leader / request clarification tools
- Message classification schema
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.events import Event, EventBus, EventType, RunContext
from agentagent.core.modes import _topological_layers
from agentagent.core.schemas import MessageClassification, parse_llm_json
from agentagent.tools.builtin import (
    FileSystemTool,
    RequestClarificationTool,
    SignalLeaderTool,
    create_default_registry,
)


# ── RunContext ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_context_check_pause_not_paused():
    """check_pause returns immediately when not paused."""
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
    )
    await ctx.check_pause()  # should not block


@pytest.mark.asyncio
async def test_run_context_cancel_raises():
    """check_pause raises CancelledError when cancelled."""
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
    )
    ctx.cancel()
    assert ctx.cancelled
    with pytest.raises(asyncio.CancelledError):
        await ctx.check_pause()


def test_run_context_mode_default():
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
    )
    assert ctx.mode == "interactive"


# ── Topological sort ────────────────────────────────────────


def test_topological_no_deps():
    """All independent subtasks land in one layer."""
    subtasks = [
        {"task": "A", "assignee": "alice"},
        {"task": "B", "assignee": "bob"},
        {"task": "C", "assignee": "carol"},
    ]
    layers = _topological_layers(subtasks)
    assert len(layers) == 1
    assert len(layers[0]) == 3


def test_topological_linear_chain():
    """A → B → C becomes three layers."""
    subtasks = [
        {"task": "A", "assignee": "a"},
        {"task": "B", "assignee": "b", "dependencies": ["A"]},
        {"task": "C", "assignee": "c", "dependencies": ["B"]},
    ]
    layers = _topological_layers(subtasks)
    assert len(layers) == 3
    assert layers[0][0]["task"] == "A"
    assert layers[1][0]["task"] == "B"
    assert layers[2][0]["task"] == "C"


def test_topological_diamond():
    """Diamond: A → (B,C) → D produces 3 layers."""
    subtasks = [
        {"task": "A", "assignee": "a"},
        {"task": "B", "assignee": "b", "dependencies": ["A"]},
        {"task": "C", "assignee": "c", "dependencies": ["A"]},
        {"task": "D", "assignee": "d", "dependencies": ["B", "C"]},
    ]
    layers = _topological_layers(subtasks)
    assert len(layers) == 3
    assert layers[0][0]["task"] == "A"
    mid_tasks = {s["task"] for s in layers[1]}
    assert mid_tasks == {"B", "C"}
    assert layers[2][0]["task"] == "D"


def test_topological_cycle_fallback():
    """Cyclic deps dump remaining subtasks in a final catch-all layer."""
    subtasks = [
        {"task": "X", "assignee": "a", "dependencies": ["Y"]},
        {"task": "Y", "assignee": "b", "dependencies": ["X"]},
        {"task": "Z", "assignee": "c"},
    ]
    layers = _topological_layers(subtasks)
    # Z is independent → layer 1.  X,Y are cyclic → layer 2
    assert len(layers) == 2
    assert layers[0][0]["task"] == "Z"
    cycle_tasks = {s["task"] for s in layers[1]}
    assert cycle_tasks == {"X", "Y"}


def test_topological_unknown_dep_ignored():
    """Dependencies that don't match any subtask are ignored."""
    subtasks = [
        {"task": "A", "assignee": "a", "dependencies": ["nonexistent"]},
    ]
    layers = _topological_layers(subtasks)
    assert len(layers) == 1
    assert layers[0][0]["task"] == "A"


def test_topological_empty():
    """Empty subtask list returns a single empty layer."""
    layers = _topological_layers([])
    assert len(layers) == 1
    assert layers[0] == []


# ── File safety limits ───────────────────────────────────────


@pytest.mark.asyncio
async def test_file_system_write_within_limits(tmp_path):
    tool = FileSystemTool(work_dir=str(tmp_path))
    result = await tool.execute(action="write", path="hello.txt", content="hi")
    data = json.loads(result)
    assert data["status"] == "written"
    assert (tmp_path / "hello.txt").read_text() == "hi"


@pytest.mark.asyncio
async def test_file_system_rejects_oversized_file(tmp_path):
    tool = FileSystemTool(work_dir=str(tmp_path))
    oversized = "x" * (1_048_576 + 1)  # 1 MB + 1 byte
    result = await tool.execute(action="write", path="big.txt", content=oversized)
    data = json.loads(result)
    assert "error" in data
    assert "too large" in data["error"].lower()


@pytest.mark.asyncio
async def test_file_system_emits_write_event(tmp_path):
    pause = asyncio.Event()
    pause.set()
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe(handler)

    ctx = RunContext(
        project_id="test123",
        event_bus=bus,
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
    )
    tool = FileSystemTool(work_dir=str(tmp_path), run_context=ctx)
    await tool.execute(action="write", path="out.txt", content="hello")

    file_events = [e for e in received if e.type == EventType.FILE_WRITTEN]
    assert len(file_events) == 1
    assert file_events[0].data["path"] == "out.txt"


# ── SignalLeaderTool ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_signal_leader_puts_on_channel():
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
    )
    tool = SignalLeaderTool(ctx)
    result = await tool.execute(message="conflict found", severity="warning")
    data = json.loads(result)
    assert data["status"] == "signal_sent"

    signal = ctx.agent_channel.get_nowait()
    assert signal["message"] == "conflict found"
    assert signal["severity"] == "warning"


# ── RequestClarificationTool ─────────────────────────────────


@pytest.mark.asyncio
async def test_request_clarification_receives_answer():
    pause = asyncio.Event()
    pause.set()
    bus = EventBus()
    queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    ctx = RunContext(
        project_id="p1",
        event_bus=bus,
        pause_event=pause,
        message_queue=queue,
        agent_channel=asyncio.Queue(),
    )
    tool = RequestClarificationTool(ctx)

    # Pre-fill a user response
    await queue.put({"message": "Use PostgreSQL", "action": "message"})

    result = await tool.execute(question="Which database?")
    data = json.loads(result)
    assert data["answer"] == "Use PostgreSQL"


@pytest.mark.asyncio
async def test_request_clarification_timeout():
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
    )
    tool = RequestClarificationTool(ctx)
    # Override timeout for test speed
    tool.TIMEOUT_SECONDS = 0.1

    result = await tool.execute(question="Timeout test?")
    data = json.loads(result)
    assert "best judgment" in data["answer"].lower()


# ── create_default_registry ──────────────────────────────────


def test_registry_interactive_mode_has_clarification():
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
        mode="interactive",
    )
    reg = create_default_registry(run_context=ctx)
    assert reg.get("signal_leader") is not None
    assert reg.get("request_clarification") is not None


def test_registry_autonomous_mode_no_clarification():
    pause = asyncio.Event()
    pause.set()
    ctx = RunContext(
        project_id="p1",
        event_bus=EventBus(),
        pause_event=pause,
        message_queue=asyncio.Queue(),
        agent_channel=asyncio.Queue(),
        mode="autonomous",
    )
    reg = create_default_registry(run_context=ctx)
    assert reg.get("signal_leader") is not None
    assert reg.get("request_clarification") is None


def test_registry_no_context_no_coordination_tools():
    reg = create_default_registry()
    assert reg.get("signal_leader") is None
    assert reg.get("request_clarification") is None


# ── MessageClassification schema ─────────────────────────────


def test_message_classification_parse():
    raw = '{"audience": "current_step", "summary": "feedback"}'
    result = parse_llm_json(raw, MessageClassification)
    assert result.audience == "current_step"


def test_message_classification_workflow():
    raw = '{"audience": "workflow", "summary": "change direction"}'
    result = parse_llm_json(raw, MessageClassification)
    assert result.audience == "workflow"


# ── New event types exist ────────────────────────────────────


def test_new_event_types_exist():
    assert EventType.USER_INPUT_RECEIVED.value == "user_input_received"
    assert EventType.FILE_WRITTEN.value == "file_written"
