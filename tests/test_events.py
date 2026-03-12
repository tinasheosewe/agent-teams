"""Tests for EventBus."""

import pytest

from agentagent.core.events import Event, EventBus, EventType


@pytest.mark.asyncio
async def test_event_bus_subscribe_and_emit():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe(handler)

    event = Event(type=EventType.AGENT_MESSAGE, data={"msg": "hello"}, project_id="p1")
    await bus.emit(event)

    assert len(received) == 1
    assert received[0].data["msg"] == "hello"


@pytest.mark.asyncio
async def test_event_bus_multiple_handlers():
    bus = EventBus()
    handler1_events = []
    handler2_events = []

    async def handler1(event: Event):
        handler1_events.append(event)

    async def handler2(event: Event):
        handler2_events.append(event)

    bus.subscribe(handler1)
    bus.subscribe(handler2)

    await bus.emit(Event(type=EventType.DECISION_MADE, data={}, project_id="p1"))

    assert len(handler1_events) == 1
    assert len(handler2_events) == 1


@pytest.mark.asyncio
async def test_event_bus_handler_error_doesnt_break():
    bus = EventBus()
    good_events = []

    async def bad_handler(event: Event):
        raise RuntimeError("oops")

    async def good_handler(event: Event):
        good_events.append(event)

    bus.subscribe(bad_handler)
    bus.subscribe(good_handler)

    await bus.emit(Event(type=EventType.COST_UPDATE, data={}, project_id="p1"))

    # Good handler still got the event
    assert len(good_events) == 1


def test_event_to_dict():
    event = Event(
        type=EventType.WORKFLOW_COMPLETE,
        data={"tokens": 1000},
        project_id="p1",
    )
    d = event.to_dict()
    assert d["type"] == "workflow_complete"
    assert d["data"]["tokens"] == 1000
    assert d["project_id"] == "p1"
    assert "timestamp" in d
