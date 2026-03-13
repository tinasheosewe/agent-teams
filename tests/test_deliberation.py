"""Tests for the organic discussion protocol (DISCUSS->SYNTHESIZE)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.agent import Agent
from agentagent.core.deliberation import (
    DeliberationConfig,
    DeliberationResult,
    TranscriptEntry,
    _format_transcript_text,
    _is_pass,
    _opening_prompt_reflect,
    _opening_prompt_think,
    _transcript_to_messages,
    converse_with_team,
    deliberate,
)
from agentagent.core.events import EventBus


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


# -- TranscriptEntry ---------------------------------------------------


def test_transcript_entry_to_dict():
    entry = TranscriptEntry(
        speaker="engineer", role="engineer", content="Let's build it.", phase="discuss",
    )
    d = entry.to_dict()
    assert d["speaker"] == "engineer"
    assert d["role"] == "engineer"
    assert d["content"] == "Let's build it."
    assert d["phase"] == "discuss"
    assert "timestamp" in d


# -- Prompt builders ----------------------------------------------------


def test_opening_prompt_think_contains_task():
    q = _opening_prompt_think("Build a REST API")
    assert "REST API" in q


def test_opening_prompt_reflect_contains_task_and_output():
    q = _opening_prompt_reflect("Build a REST API", "Here is the API code...")
    assert "REST API" in q
    assert "API code" in q


# -- PASS detection -----------------------------------------------------


def test_is_pass_exact():
    assert _is_pass("PASS")
    assert _is_pass("pass")
    assert _is_pass("  PASS  ")
    assert _is_pass("Pass")


def test_is_pass_false():
    assert not _is_pass("I think we should PASS on this")
    assert not _is_pass("Not PASS")
    assert not _is_pass("")


# -- Transcript helpers -------------------------------------------------


def test_transcript_to_messages():
    entries = [
        TranscriptEntry(speaker="mod", role="moderator", content="Question?", phase="discuss"),
        TranscriptEntry(speaker="eng", role="engineer", content="Answer.", phase="discuss"),
    ]
    msgs = _transcript_to_messages(entries)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert "[moderator]" in msgs[0].content


def test_format_transcript_text():
    entries = [
        TranscriptEntry(speaker="mod", role="moderator", content="Question?", phase="discuss"),
        TranscriptEntry(speaker="eng", role="engineer", content="Answer.", phase="discuss"),
    ]
    text = _format_transcript_text(entries)
    assert "moderator" in text
    assert "engineer" in text
    assert "Question?" in text


# -- deliberate() single agent -----------------------------------------


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_single_agent_short_circuit(mock_litellm):
    """Single agent: gets perspective then goes straight to synthesis."""
    agent_resp = _make_completion_response("I think we should use REST.")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Team agrees on REST API approach.",
        "mode_selection": "execution",
        "mode_reasoning": "This is a build task.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(side_effect=[agent_resp, synth_resp])

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Build a REST API",
        context="",
        historian=historian,
        config=config,
    )

    assert isinstance(result, DeliberationResult)
    assert result.mode_selection == "execution"
    assert len(result.transcript) > 0
    assert any(e.phase == "discuss" for e in result.transcript)
    assert any(e.phase == "synthesis" for e in result.transcript)


# -- deliberate() multi-agent convergence ------------------------------


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_multi_agent_converges_on_all_pass(mock_litellm):
    """Two agents: round 1 both speak, round 2 both PASS -> convergence."""
    agent1_r1 = _make_completion_response("Use microservices.")
    agent2_r1 = _make_completion_response("Use monolith.")
    agent1_r2 = _make_completion_response("PASS")
    agent2_r2 = _make_completion_response("PASS")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Team discussed micro vs mono and converged.",
        "mode_selection": "generative",
        "mode_reasoning": "Need creative exploration.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[agent1_r1, agent2_r1, agent1_r2, agent2_r2, synth_resp]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Design the system",
        context="",
        historian=historian,
        config=config,
    )

    assert isinstance(result, DeliberationResult)
    assert result.mode_selection == "generative"
    discuss_entries = [e for e in result.transcript if e.phase == "discuss" and e.role != "moderator"]
    assert len(discuss_entries) == 2  # only round 1 responses


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_max_rounds_cap(mock_litellm):
    """Discussion hits max_rounds without convergence and still synthesizes."""
    agent_resp = _make_completion_response("I disagree, let me explain...")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Capped at max rounds.",
        "mode_selection": "decision",
        "mode_reasoning": "Need to decide.",
        "open_items": ["architecture"],
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[agent_resp, agent_resp, agent_resp, agent_resp, synth_resp]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=2)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Decide DB",
        context="",
        historian=historian,
        config=config,
    )

    assert result.summary == "Capped at max rounds."


# -- deliberate() reflection mode --------------------------------------


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_reflect_mode(mock_litellm):
    """Reflection mode (prior_output set) uses ReflectionSynthesis."""
    agent1_resp = _make_completion_response("Output quality is good.")
    agent2_resp = _make_completion_response("I agree, looks solid.")
    agent1_pass = _make_completion_response("PASS")
    agent2_pass = _make_completion_response("PASS")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Team accepts the output.",
        "verdict": "accept",
        "revision_guidance": "",
        "confidence": 0.9,
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[agent1_resp, agent2_resp, agent1_pass, agent2_pass, synth_resp]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Build feature X",
        context="",
        historian=historian,
        config=config,
        prior_output="The completed feature X implementation...",
    )

    assert result.verdict == "accept"
    assert result.mode_selection is None


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_reflect_revise(mock_litellm):
    """Reflection with revise verdict returns revision_guidance."""
    agent1_resp = _make_completion_response("Missing error handling.")
    agent2_resp = _make_completion_response("Needs better tests.")
    agent1_pass = _make_completion_response("PASS")
    agent2_pass = _make_completion_response("PASS")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Output needs revision.",
        "verdict": "revise",
        "revision_guidance": "Add error handling and improve test coverage.",
        "confidence": 0.4,
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[agent1_resp, agent2_resp, agent1_pass, agent2_pass, synth_resp]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Build feature X",
        context="",
        historian=historian,
        config=config,
        prior_output="Partial implementation...",
    )

    assert result.verdict == "revise"
    assert result.revision_guidance is not None
    assert "error handling" in result.revision_guidance


# -- Spiral detection --------------------------------------------------


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_spiral_check_triggers(mock_litellm):
    """Spiral check fires at round 3 and injects nudge when circular."""
    agent_resp = _make_completion_response("I still disagree with the approach.")
    spiral_resp = _make_completion_response(json.dumps({
        "is_circular": True,
        "reason": "Same argument repeated",
        "redirect_topic": "Focus on constraints",
    }))
    agent_pass = _make_completion_response("PASS")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Converged after nudge.",
        "mode_selection": "generative",
        "mode_reasoning": "Creative.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[
            # Round 1
            agent_resp, agent_resp,
            # Round 2
            agent_resp, agent_resp,
            # Round 3
            agent_resp, agent_resp,
            # Spiral check after round 3
            spiral_resp,
            # Round 4
            agent_pass, agent_pass,
            # Synthesis
            synth_resp,
        ]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=6, spiral_check_interval=3)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Decide architecture",
        context="",
        historian=historian,
        config=config,
    )

    moderator_entries = [e for e in result.transcript if e.phase == "moderator"]
    assert len(moderator_entries) >= 1
    assert any(
        "circular" in e.content.lower() or "circles" in e.content.lower()
        for e in moderator_entries
    )


# -- Events ------------------------------------------------------------


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_emits_events(mock_litellm):
    """Deliberation emits start, cycle, and complete events."""
    agent_resp = _make_completion_response("My perspective.")
    agent_pass = _make_completion_response("PASS")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Summary.",
        "mode_selection": "generative",
        "mode_reasoning": "Creative task.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[agent_resp, agent_resp, agent_pass, agent_pass, synth_resp]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    event_bus = EventBus()
    events = []
    event_bus.subscribe(lambda e: events.append(e))

    await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Build it",
        context="",
        historian=historian,
        config=config,
        event_bus=event_bus,
        project_id="test-proj",
    )

    event_types = [e.type.value for e in events]
    assert "deliberation_start" in event_types
    assert "deliberation_cycle" in event_types
    assert "deliberation_complete" in event_types


# -- converse_with_team ------------------------------------------------


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_converse_with_team(mock_litellm):
    """converse_with_team wraps deliberate with user_message as task."""
    agent_resp = _make_completion_response("Good question, I think we should...")
    agent_pass = _make_completion_response("PASS")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Discussion about user question.",
        "mode_selection": "generative",
        "mode_reasoning": "Exploratory.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(
        side_effect=[agent_resp, agent_resp, agent_pass, agent_pass, synth_resp]
    )

    historian = MagicMock()
    historian.check_circular = AsyncMock(return_value=None)

    config = DeliberationConfig(max_rounds=4)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await converse_with_team(
        moderator_agent=moderator,
        agents=agents,
        user_message="Why did you choose microservices?",
        context="Prior architecture discussion",
        historian=historian,
        config=config,
    )

    assert isinstance(result, DeliberationResult)
    assert result.summary
