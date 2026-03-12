"""Tests for the Moderator."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.config import InteractionMode
from agentagent.core.agent import Agent
from agentagent.core.events import EventBus
from agentagent.core.moderator import Moderator
from agentagent.core.modes import ModeResult


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


def test_mode_selection_execution():
    mod = Moderator(model="gpt-4o", preferred_modes=[InteractionMode.GENERATIVE])
    assert mod.select_mode("implement the login feature") == "execution"
    assert mod.select_mode("build the API") == "execution"
    assert mod.select_mode("write code for the handler") == "execution"


def test_mode_selection_evaluative():
    mod = Moderator(model="gpt-4o", preferred_modes=[InteractionMode.GENERATIVE])
    assert mod.select_mode("review the PR") == "evaluative"
    assert mod.select_mode("evaluate this design") == "evaluative"
    assert mod.select_mode("test the system") == "evaluative"


def test_mode_selection_decision():
    mod = Moderator(model="gpt-4o", preferred_modes=[InteractionMode.GENERATIVE])
    assert mod.select_mode("choose between React and Vue") == "decision"
    assert mod.select_mode("decide on the database") == "decision"


def test_mode_selection_generative():
    mod = Moderator(model="gpt-4o", preferred_modes=[InteractionMode.GENERATIVE])
    assert mod.select_mode("design the architecture") == "generative"
    assert mod.select_mode("brainstorm ideas") == "generative"
    assert mod.select_mode("propose a solution") == "generative"


def test_mode_selection_fallback():
    mod = Moderator(model="gpt-4o", preferred_modes=[InteractionMode.EVALUATIVE])
    # No keyword matches — falls back to first preferred mode
    assert mod.select_mode("do something unrelated") == "evaluative"


def test_should_compress():
    mod = Moderator(model="gpt-4o", preferred_modes=[], context_token_limit=100_000)
    assert not mod.should_compress(50_000)
    assert mod.should_compress(80_000)


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_evaluate_completeness(mock_litellm):
    complete_response = json.dumps({
        "complete": True,
        "reasoning": "All criteria met",
        "missing": [],
    })
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(complete_response)
    )

    mod = Moderator(model="gpt-4o", preferred_modes=[])
    result = ModeResult(content="Full implementation here", confidence=0.9)

    is_complete, reasoning = await mod.evaluate_completeness("Build the API", result)
    assert is_complete
    assert "criteria" in reasoning.lower()


# ── _challenge_round() ───────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_challenge_round_agent_agrees(mock_litellm):
    """Agent agrees with proposed mode — mode stays the same."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(
            json.dumps({"agree": True, "suggested_mode": "generative", "reason": "looks right"})
        )
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer"), _make_agent("architect")]

    result = await mod._challenge_round(agents, "generative", "Design something", "proj1", None)
    assert result == "generative"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_challenge_round_agent_objects(mock_litellm):
    """Agent disagrees and suggests a valid alternative — mode changes."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(
            json.dumps({"agree": False, "suggested_mode": "execution", "reason": "this is a build task"})
        )
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer"), _make_agent("architect")]

    result = await mod._challenge_round(agents, "generative", "Build the API", "proj1", None)
    assert result == "execution"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_challenge_round_invalid_mode_suggestion(mock_litellm):
    """Agent suggests a non-existent mode — original mode kept."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(
            json.dumps({"agree": False, "suggested_mode": "nonexistent_mode", "reason": "why not"})
        )
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer"), _make_agent("architect")]

    result = await mod._challenge_round(agents, "generative", "Do something", "proj1", None)
    assert result == "generative"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_challenge_round_garbage_json(mock_litellm):
    """LLM returns unparseable JSON in challenge — original mode kept."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("I think generative is fine!")
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer"), _make_agent("architect")]

    result = await mod._challenge_round(agents, "evaluative", "Review code", "proj1", None)
    assert result == "evaluative"


@pytest.mark.asyncio
async def test_challenge_round_single_agent_skipped():
    """Challenge round is skipped with only 1 agent."""
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer")]

    result = await mod._challenge_round(agents, "execution", "Build it", "proj1", None)
    assert result == "execution"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_challenge_round_emits_event(mock_litellm):
    """Challenge round emits event when mode is changed."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(
            json.dumps({"agree": False, "suggested_mode": "decision", "reason": "need to decide"})
        )
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer"), _make_agent("architect")]
    event_bus = EventBus()
    events = []

    async def capture(e):
        events.append(e)

    event_bus.subscribe(capture)

    result = await mod._challenge_round(agents, "generative", "Choose a DB", "proj1", event_bus)
    assert result == "decision"
    assert len(events) == 1
    assert "challenge" in events[0].data["phase"]


# ── run_round() ───────────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_run_round_forced_mode(mock_litellm):
    """Forced mode bypasses selection and challenge, executes correctly."""
    # forced_mode sets mode but challenge round still runs (1 call)
    # Generative mode with 2 agents: 2 proposals + 2 scoring + 1 synthesis
    # Total: 1 challenge + 2 proposals + 2 scores + 1 synthesis = 6 calls
    challenge_resp = _make_completion_response(json.dumps({"agree": True}))
    proposal_resp = _make_completion_response("Proposal: solid architecture approach.")
    score_resp = _make_completion_response(json.dumps(
        {"scores": [{"agent": "engineer", "score": 8, "reasoning": "solid"},
                    {"agent": "architect", "score": 7, "reasoning": "ok"}]}
    ))
    synthesis_resp = _make_completion_response("Final synthesis: combined approach.")

    mock_litellm.acompletion = AsyncMock(
        side_effect=[
            challenge_resp,                  # 1 challenge
            proposal_resp, proposal_resp,    # 2 proposals
            score_resp, score_resp,          # 2 scoring
            synthesis_resp,                  # 1 synthesis
        ]
    )

    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("engineer"), _make_agent("architect")]

    result = await mod.run_round(
        agents=agents,
        task="Design the system",
        context="Building a new SaaS product",
        forced_mode="generative",
    )

    assert isinstance(result, ModeResult)
    assert len(result.content) > 0
    assert result.total_input_tokens > 0


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_run_round_unknown_mode_fallback(mock_litellm):
    """Unknown forced mode falls back to generative."""
    generic_resp = _make_completion_response("Generic response")
    score_resp = _make_completion_response(json.dumps(
        {"scores": [{"agent": "a", "score": 5, "reasoning": "ok"},
                    {"agent": "b", "score": 6, "reasoning": "ok"}]}
    ))
    # Challenge (1 agent check) + 2 proposals + 2 scores + 1 synthesis = 6
    mock_litellm.acompletion = AsyncMock(
        side_effect=[
            _make_completion_response(json.dumps({"agree": True})),  # challenge
            generic_resp, generic_resp,    # proposals
            score_resp, score_resp,        # scoring
            generic_resp,                  # synthesis
        ]
    )

    mod = Moderator(model="gpt-4o", preferred_modes=[])
    agents = [_make_agent("a"), _make_agent("b")]

    result = await mod.run_round(
        agents=agents, task="Do something", context="", forced_mode="nonexistent"
    )
    assert isinstance(result, ModeResult)


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_evaluate_completeness_incomplete(mock_litellm):
    """Evaluate completeness returns False when LLM says incomplete."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(
            json.dumps({"complete": False, "reasoning": "Missing error handling", "missing": ["error handling"]})
        )
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    result = ModeResult(content="Partial implementation")

    is_complete, reasoning = await mod.evaluate_completeness("Build feature X", result)
    assert not is_complete
    assert "error handling" in reasoning.lower()


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_evaluate_completeness_garbage_returns_false(mock_litellm):
    """Evaluate completeness returns (False, raw_content) when LLM returns garbage."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("I'm not sure what to say here, let me think...")
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    result = ModeResult(content="Some output")

    is_complete, reasoning = await mod.evaluate_completeness("Build it", result)
    assert not is_complete
    assert "think" in reasoning.lower()


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_evaluate_completeness_with_gate_criteria(mock_litellm):
    """Gate criteria are included in the completeness evaluation prompt."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(
            json.dumps({"complete": True, "reasoning": "All acceptance criteria met", "missing": []})
        )
    )
    mod = Moderator(model="gpt-4o", preferred_modes=[])
    result = ModeResult(content="Implementation with tests")
    gate = {"description": "Must have unit tests", "automated_checks": ["pytest"]}

    is_complete, reasoning = await mod.evaluate_completeness("Build it", result, gate_criteria=gate)
    assert is_complete

    # Verify gate criteria were included in the prompt
    call_args = mock_litellm.acompletion.call_args
    prompt = call_args[1]["messages"][1]["content"]
    assert "unit tests" in prompt.lower()
