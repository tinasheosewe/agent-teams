"""Tests for interaction modes with mocked LLM."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.agent import Agent, Message
from agentagent.core.events import EventBus
from agentagent.core.modes import (
    DecisionMode,
    EvaluativeMode,
    ExecutionMode,
    GenerativeMode,
    ModeResult,
)


def _make_agent(role: str) -> Agent:
    return Agent(role=role, persona=f"You are a {role}.", model="gpt-4o")


def _make_completion_response(content: str):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.prompt_tokens = 50
    usage.completion_tokens = 25
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_generative_mode(mock_litellm):
    # Proposal phase: each agent produces a proposal
    proposal1 = _make_completion_response("Use React framework for the frontend")
    proposal2 = _make_completion_response("Use Vue framework for the frontend")

    # Scoring phase: both return scores
    scores = json.dumps({
        "scores": [
            {"agent": "designer", "score": 8, "reasoning": "good"},
            {"agent": "engineer", "score": 7, "reasoning": "ok"},
        ]
    })
    score_resp = _make_completion_response(scores)

    # Synthesis phase: winner synthesizes
    synthesis = _make_completion_response("Final: Use React with TypeScript")

    mock_litellm.acompletion = AsyncMock(
        side_effect=[proposal1, proposal2, score_resp, score_resp, synthesis]
    )

    mode = GenerativeMode()
    agents = [_make_agent("designer"), _make_agent("engineer")]
    result = await mode.execute(agents, "Choose a frontend framework", "Building a web app")

    assert isinstance(result, ModeResult)
    assert result.content  # Has synthesized content


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_evaluative_mode(mock_litellm):
    review = json.dumps({
        "issues": [{"issue": "Missing error handling", "severity": "major", "suggestion": "Add try/catch"}],
        "strengths": ["Clean code structure"],
        "overall_assessment": "needs_changes",
    })
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(review)
    )

    mode = EvaluativeMode()
    agents = [_make_agent("reviewer")]
    result = await mode.execute(agents, "Review this code", "def hello(): pass")

    assert isinstance(result, ModeResult)
    data = json.loads(result.content)
    assert data["overall_assessment"] == "needs_changes"
    assert len(data["major_issues"]) == 1


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_execution_mode(mock_litellm):
    decomposition = json.dumps({
        "subtasks": [
            {"assignee": "engineer", "task": "Build the API", "dependencies": []},
        ]
    })
    subtask_result = _make_completion_response("API built successfully")
    integration = _make_completion_response("All integrated")

    mock_litellm.acompletion = AsyncMock(
        side_effect=[
            _make_completion_response(decomposition),
            subtask_result,
            integration,
        ]
    )

    mode = ExecutionMode()
    agents = [_make_agent("engineer")]
    result = await mode.execute(agents, "Build the system", "Context here")

    assert isinstance(result, ModeResult)
    assert result.content == "All integrated"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_decision_mode(mock_litellm):
    options = json.dumps({
        "options": [
            {"name": "PostgreSQL", "pros": ["mature"], "cons": ["complex"], "risks": []},
            {"name": "SQLite", "pros": ["simple"], "cons": ["limited"], "risks": []},
        ],
        "recommendation": "PostgreSQL",
        "reasoning": "Better for production",
    })
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(options)
    )

    mode = DecisionMode()
    agents = [_make_agent("architect")]
    result = await mode.execute(agents, "Choose a database", "Building a web app")

    assert isinstance(result, ModeResult)
    assert result.decisions


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_generative_mode_with_event_bus(mock_litellm):
    """Verify events are emitted during mode execution."""
    proposal = _make_completion_response("My proposal")
    scores = json.dumps({
        "scores": [{"agent": "tester", "score": 9, "reasoning": "great"}]
    })
    score_resp = _make_completion_response(scores)
    synthesis = _make_completion_response("Final output")

    mock_litellm.acompletion = AsyncMock(
        side_effect=[proposal, score_resp, synthesis]
    )

    event_bus = EventBus()
    events_received = []

    async def handler(event):
        events_received.append(event)

    event_bus.subscribe(handler)

    mode = GenerativeMode()
    agents = [_make_agent("tester")]
    await mode.execute(agents, "task", "context", event_bus=event_bus, project_id="p1")

    assert len(events_received) > 0
