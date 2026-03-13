"""Tests for the Moderator — covers both legacy and deliberation paths."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.config import InteractionMode, ThinkingDepth
from agentagent.core.agent import Agent
from agentagent.core.events import EventBus
from agentagent.core.moderator import LoopResult, Moderator
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


# ── LoopResult ────────────────────────────────────────────────


def test_loop_result_total_tokens():
    lr = LoopResult(
        content="test",
        thinking_tokens=(100, 50),
        execution_tokens=(200, 100),
        reflection_tokens=(80, 40),
    )
    assert lr.total_input_tokens == 380
    assert lr.total_output_tokens == 190


def test_loop_result_defaults():
    lr = LoopResult(content="test")
    assert lr.total_input_tokens == 0
    assert lr.total_output_tokens == 0
    assert lr.confidence == 0.8
    assert lr.rounds_used == 0
    assert lr.transcript == []


# ── should_compress ───────────────────────────────────────────


def test_should_compress_under_threshold():
    mod = Moderator(model="gpt-4o", preferred_modes=[], context_token_limit=100_000)
    assert not mod.should_compress(50_000)


def test_should_compress_over_threshold():
    mod = Moderator(model="gpt-4o", preferred_modes=[], context_token_limit=100_000)
    assert mod.should_compress(80_000)


# ── Legacy path (_run_legacy via run_task_loop) ───────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_legacy_path_generative(mock_litellm):
    """Legacy path (deliberation disabled) runs a generative mode execution."""
    proposal_resp = _make_completion_response("Proposal: build it this way.")
    score_resp = _make_completion_response(json.dumps(
        {"scores": [{"agent": "engineer", "score": 8, "reasoning": "solid"},
                    {"agent": "architect", "score": 7, "reasoning": "ok"}]}
    ))
    synthesis_resp = _make_completion_response("Final synthesis: combined approach.")

    mock_litellm.acompletion = AsyncMock(
        side_effect=[
            proposal_resp, proposal_resp,    # 2 proposals
            score_resp, score_resp,          # 2 scoring
            synthesis_resp,                  # 1 synthesis
        ]
    )

    mod = Moderator(
        model="gpt-4o",
        preferred_modes=[InteractionMode.GENERATIVE],
        enable_deliberation=False,
    )
    agents = [_make_agent("engineer"), _make_agent("architect")]

    # Historian/stenographer not used in legacy path
    result = await mod.run_task_loop(
        agents=agents,
        task="Design the system",
        context="Building a new SaaS product",
        historian=MagicMock(),
        stenographer=MagicMock(),
    )

    assert isinstance(result, LoopResult)
    assert len(result.content) > 0
    assert result.rounds_used == 1
    assert result.execution_tokens[0] > 0


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_legacy_path_emits_mode_selected(mock_litellm):
    """Legacy path emits TEAM_MODE_SELECTED event."""
    proposal_resp = _make_completion_response("Proposal.")
    score_resp = _make_completion_response(json.dumps(
        {"scores": [{"agent": "a", "score": 5, "reasoning": "ok"}]}
    ))
    synthesis_resp = _make_completion_response("Synthesis.")

    mock_litellm.acompletion = AsyncMock(
        side_effect=[proposal_resp, score_resp, synthesis_resp]
    )

    mod = Moderator(
        model="gpt-4o",
        preferred_modes=[InteractionMode.GENERATIVE],
        enable_deliberation=False,
    )
    agents = [_make_agent("a")]
    event_bus = EventBus()
    events = []
    event_bus.subscribe(lambda e: events.append(e))

    await mod.run_task_loop(
        agents=agents,
        task="Think",
        context="",
        historian=MagicMock(),
        stenographer=MagicMock(),
        event_bus=event_bus,
    )

    mode_events = [e for e in events if e.type.value == "team_mode_selected"]
    assert len(mode_events) == 1
    assert mode_events[0].data["source"] == "legacy"


# ── Constructor config ────────────────────────────────────────


def test_moderator_config_flags():
    mod = Moderator(
        model="gpt-4o",
        preferred_modes=[InteractionMode.EXECUTION],
        enable_deliberation=True,
        thinking_depth=ThinkingDepth.PERSPECTIVE_ONLY,
        max_deliberation_cycles=5,
    )
    assert mod._enable_deliberation is True
    assert mod._thinking_depth == ThinkingDepth.PERSPECTIVE_ONLY
    assert mod._max_deliberation_cycles == 5


def test_moderator_defaults():
    mod = Moderator(
        model="gpt-4o",
        preferred_modes=[InteractionMode.GENERATIVE],
    )
    assert mod._enable_deliberation is False
    assert mod._thinking_depth == ThinkingDepth.FULL
    assert mod._max_deliberation_cycles == 3
