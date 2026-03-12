"""Tests for the Moderator."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.config import InteractionMode
from agentagent.core.agent import Agent
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
