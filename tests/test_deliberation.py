"""Tests for the board-based deliberation protocol."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.agent import Agent
from agentagent.core.deliberation import (
    Board,
    DeliberationConfig,
    DeliberationResult,
    Point,
    PointStatus,
    Stance,
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


def _board_turn(
    new_points: list[dict] | None = None,
    reactions: list[dict] | None = None,
    amendments: list[dict] | None = None,
    done: bool = False,
) -> str:
    """Build a valid BoardTurnResponse JSON string for mocking."""
    return json.dumps({
        "new_points": new_points or [],
        "reactions": reactions or [],
        "amendments": amendments or [],
        "done": done,
    })


# ── Board data model ──────────────────────────────────────────


class TestBoard:
    """Unit tests for the Board, Point, and related data types."""

    def test_add_point(self):
        board = Board()
        pt = board.add_point("Use REST", "engineer")
        assert pt.id == 1
        assert pt.current.claim == "Use REST"
        assert pt.author == "engineer"
        assert pt.current_version == 1

    def test_ids_increment(self):
        board = Board()
        p1 = board.add_point("A", "eng")
        p2 = board.add_point("B", "arch")
        assert p1.id == 1
        assert p2.id == 2

    def test_get_point(self):
        board = Board()
        board.add_point("X", "eng")
        assert board.get_point(1) is not None
        assert board.get_point(99) is None

    def test_point_status_single_agent_consensus(self):
        """Single-agent roster → automatic consensus."""
        board = Board()
        pt = board.add_point("Claim", "eng")
        assert pt.status(["eng"]) == PointStatus.CONSENSUS

    def test_point_status_open_no_reactions(self):
        board = Board()
        pt = board.add_point("Claim", "eng")
        assert pt.status(["eng", "arch"]) == PointStatus.OPEN

    def test_point_status_consensus_all_agree(self):
        board = Board()
        pt = board.add_point("Claim", "eng")
        pt.react("arch", Stance.AGREE, "Sounds good")
        assert pt.status(["eng", "arch"]) == PointStatus.CONSENSUS

    def test_point_status_contested_on_disagree(self):
        board = Board()
        pt = board.add_point("Claim", "eng")
        pt.react("arch", Stance.DISAGREE, "No way")
        assert pt.status(["eng", "arch"]) == PointStatus.CONTESTED

    def test_point_status_question_counts_as_reacted(self):
        board = Board()
        pt = board.add_point("Claim", "eng")
        pt.react("arch", Stance.QUESTION, "Why?")
        assert pt.status(["eng", "arch"]) == PointStatus.CONSENSUS

    def test_amend_bumps_version_and_clears_reactions(self):
        board = Board()
        pt = board.add_point("Original", "eng")
        pt.react("arch", Stance.AGREE, "Ok")
        assert pt.current_version == 1
        assert "arch" in pt.current.reactions

        pt.amend("Revised", amended_by="arch", reason="Needs clarity")
        assert pt.current_version == 2
        assert pt.current.claim == "Revised"
        assert len(pt.current.reactions) == 0  # Fresh version, no reactions

    def test_board_is_settled(self):
        board = Board()
        p1 = board.add_point("A", "eng")
        p1.react("arch", Stance.AGREE, "Ok")
        assert board.is_settled(["eng", "arch"])

    def test_board_not_settled_with_open_point(self):
        board = Board()
        board.add_point("A", "eng")
        assert not board.is_settled(["eng", "arch"])

    def test_board_settled_with_contested(self):
        """Contested is NOT open — board is settled."""
        board = Board()
        p1 = board.add_point("A", "eng")
        p1.react("arch", Stance.DISAGREE, "No")
        assert board.is_settled(["eng", "arch"])

    def test_board_render_empty(self):
        board = Board()
        text = board.render(["eng"])
        assert "empty" in text.lower()

    def test_board_render_consensus_compact(self):
        board = Board()
        p1 = board.add_point("Use REST", "eng")
        p1.react("arch", Stance.AGREE, "Fine")
        text = board.render(["eng", "arch"])
        assert "CONSENSUS" in text
        assert "POINT 1" in text

    def test_board_render_contested_full(self):
        board = Board()
        p1 = board.add_point("Use REST", "eng")
        p1.react("arch", Stance.DISAGREE, "Bad idea")
        text = board.render(["eng", "arch"])
        assert "CONTESTED" in text.lower() or "contested" in text

    def test_three_agent_consensus(self):
        board = Board()
        pt = board.add_point("Claim", "eng")
        pt.react("arch", Stance.AGREE, "Ok")
        # designer hasn't reacted → OPEN
        assert pt.status(["eng", "arch", "designer"]) == PointStatus.OPEN
        pt.react("designer", Stance.AGREE, "Yep")
        assert pt.status(["eng", "arch", "designer"]) == PointStatus.CONSENSUS


# ── TranscriptEntry ───────────────────────────────────────────


def test_transcript_entry_to_dict():
    entry = TranscriptEntry(
        speaker="engineer", role="engineer", content="Let's build it.", phase="board_turn",
    )
    d = entry.to_dict()
    assert d["speaker"] == "engineer"
    assert d["role"] == "engineer"
    assert d["content"] == "Let's build it."
    assert d["phase"] == "board_turn"
    assert "timestamp" in d


# ── Prompt builders ───────────────────────────────────────────


def test_opening_prompt_think_contains_task():
    q = _opening_prompt_think("Build a REST API")
    assert "REST API" in q


def test_opening_prompt_reflect_contains_task_and_output():
    q = _opening_prompt_reflect("Build a REST API", "Here is the API code...")
    assert "REST API" in q
    assert "API code" in q


# ── PASS detection ────────────────────────────────────────────


def test_is_pass_exact():
    assert _is_pass("PASS")
    assert _is_pass("pass")
    assert _is_pass("  PASS  ")
    assert _is_pass("Pass")


def test_is_pass_false():
    assert not _is_pass("I think we should PASS on this")
    assert not _is_pass("Not PASS")
    assert not _is_pass("")


# ── Transcript helpers ────────────────────────────────────────


def test_transcript_to_messages():
    entries = [
        TranscriptEntry(speaker="mod", role="moderator", content="Question?", phase="board_turn"),
        TranscriptEntry(speaker="eng", role="engineer", content="Answer.", phase="board_turn"),
    ]
    msgs = _transcript_to_messages(entries)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert "[moderator]" in msgs[0].content


def test_format_transcript_text():
    entries = [
        TranscriptEntry(speaker="mod", role="moderator", content="Question?", phase="board_turn"),
        TranscriptEntry(speaker="eng", role="engineer", content="Answer.", phase="board_turn"),
    ]
    text = _format_transcript_text(entries)
    assert "moderator" in text
    assert "engineer" in text
    assert "Question?" in text


# ── DeliberationConfig backward compat ────────────────────────


def test_config_max_rounds_alias():
    """max_rounds is accepted as a legacy alias for max_turns."""
    config = DeliberationConfig(max_rounds=10)
    assert config.max_turns == 10


def test_config_max_turns_default():
    config = DeliberationConfig()
    assert config.max_turns == 30


def test_config_max_turns_explicit():
    config = DeliberationConfig(max_turns=5)
    assert config.max_turns == 5


# ── deliberate() single agent ─────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_single_agent_short_circuit(mock_litellm):
    """Single agent: free-form perspective then straight to synthesis."""
    agent_resp = _make_completion_response("I think we should use REST.")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Team agrees on REST API approach.",
        "mode_selection": "execution",
        "mode_reasoning": "This is a build task.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(side_effect=[agent_resp, synth_resp])

    historian = MagicMock()
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
    assert any(e.phase == "board_turn" for e in result.transcript)
    assert any(e.phase == "synthesis" for e in result.transcript)
    # Board should have one point from the single agent
    assert result.board is not None
    assert len(result.board.points) == 1


# ── deliberate() multi-agent convergence ──────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_multi_agent_board_convergence(mock_litellm):
    """Two agents converge: raise points → react agree → done → done."""
    responses = [
        # Turn 1 (engineer): raise a point
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Use microservices for scalability."}],
        )),
        # Turn 2 (architect): react agree + raise own point
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Use PostgreSQL for persistence."}],
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "Scalable."}],
        )),
        # Turn 3 (engineer): react agree to point 2
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 2, "stance": "agree", "reasoning": "Solid choice."}],
        )),
        # Turn 4 (architect): done (no actions)
        _make_completion_response(_board_turn(done=True)),
        # Turn 5 (engineer): done (no actions)
        _make_completion_response(_board_turn(done=True)),
        # Synthesis
        _make_completion_response(json.dumps({
            "summary": "Team converged on microservices + PostgreSQL.",
            "mode_selection": "generative",
            "mode_reasoning": "Creative task.",
            "open_items": [],
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
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
    assert result.board is not None
    assert len(result.board.points) == 2
    # Both points should be consensus
    statuses = result.board.all_status(["engineer", "architect"])
    assert all(s == PointStatus.CONSENSUS for s in statuses.values())


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_max_turns_cap(mock_litellm):
    """Discussion hits max_turns without convergence and still synthesizes."""
    # 2 turns, agents keep raising points without converging
    responses = [
        _make_completion_response(_board_turn(
            new_points=[{"claim": "We need containers."}],
        )),
        _make_completion_response(_board_turn(
            new_points=[{"claim": "We need serverless."}],
            reactions=[{"point_id": 1, "stance": "disagree", "reasoning": "Too heavy."}],
        )),
        # Synthesis after max_turns=2
        _make_completion_response(json.dumps({
            "summary": "Capped at max turns.",
            "mode_selection": "decision",
            "mode_reasoning": "Need to decide.",
            "open_items": ["deployment model"],
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=2)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Decide deployment",
        context="",
        historian=historian,
        config=config,
    )

    assert result.summary == "Capped at max turns."


# ── deliberate() reflection mode ──────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_reflect_accept(mock_litellm):
    """Reflection: agents agree output is good → accept."""
    responses = [
        # Turn 1 (engineer): raise a positive point
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Output quality is solid."}],
        )),
        # Turn 2 (architect): agree + done
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "Looks good."}],
        )),
        # Turn 3 (engineer): done
        _make_completion_response(_board_turn(done=True)),
        # Turn 4 (architect): done
        _make_completion_response(_board_turn(done=True)),
        # Reflection synthesis
        _make_completion_response(json.dumps({
            "summary": "Team accepts the output.",
            "verdict": "accept",
            "revision_guidance": "",
            "confidence": 0.9,
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
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
    """Reflection: agents find issues → revise verdict."""
    responses = [
        # Turn 1 (engineer): raise concern
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Missing error handling."}],
        )),
        # Turn 2 (architect): agree + raise own concern
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Needs better tests."}],
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "Critical gap."}],
        )),
        # Turn 3 (engineer): agree to point 2
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 2, "stance": "agree", "reasoning": "Yes, important."}],
        )),
        # Turn 4 (architect): done
        _make_completion_response(_board_turn(done=True)),
        # Turn 5 (engineer): done
        _make_completion_response(_board_turn(done=True)),
        # Reflection synthesis
        _make_completion_response(json.dumps({
            "summary": "Output needs revision.",
            "verdict": "revise",
            "revision_guidance": "Add error handling and improve test coverage.",
            "confidence": 0.4,
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
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


# ── Contested points don't block convergence ──────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_contested_points_dont_block(mock_litellm):
    """When agents disagree but all say done, deliberation completes."""
    responses = [
        # Turn 1 (engineer): raise point
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Use GraphQL."}],
        )),
        # Turn 2 (architect): disagree
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 1, "stance": "disagree", "reasoning": "REST is simpler."}],
        )),
        # Turn 3 (engineer): done (disagree invalidated done for others)
        _make_completion_response(_board_turn(done=True)),
        # Turn 4 (architect): done
        _make_completion_response(_board_turn(done=True)),
        # Synthesis
        _make_completion_response(json.dumps({
            "summary": "Disagreement on API style — contested.",
            "mode_selection": "decision",
            "mode_reasoning": "Need to resolve disagreement.",
            "open_items": ["API style"],
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Design API",
        context="",
        historian=historian,
        config=config,
    )

    assert result.board is not None
    statuses = result.board.all_status(["engineer", "architect"])
    assert PointStatus.CONTESTED in statuses.values()
    assert result.summary  # Synthesis still produced


# ── Amendment tests ───────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_amendment_resets_approvals(mock_litellm):
    """Amendment bumps version, prior reactions invalidated, re-approval needed."""
    responses = [
        # Turn 1 (engineer): raise point
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Use REST."}],
        )),
        # Turn 2 (architect): agree to point 1
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "Fine."}],
        )),
        # Turn 3 (engineer): amend point 1 → resets architect's approval
        _make_completion_response(_board_turn(
            amendments=[{"point_id": 1, "new_claim": "Use REST with HATEOAS.", "reason": "Better discoverability."}],
        )),
        # Turn 4 (architect): re-approve amended point
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "HATEOAS is good."}],
        )),
        # Turn 5 (engineer): done
        _make_completion_response(_board_turn(done=True)),
        # Turn 6 (architect): done
        _make_completion_response(_board_turn(done=True)),
        # Synthesis
        _make_completion_response(json.dumps({
            "summary": "Agreed on REST with HATEOAS.",
            "mode_selection": "execution",
            "mode_reasoning": "Ready to build.",
            "open_items": [],
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
    agents = [_make_agent("engineer"), _make_agent("architect")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Design API",
        context="",
        historian=historian,
        config=config,
    )

    assert result.board is not None
    pt = result.board.get_point(1)
    assert pt is not None
    assert pt.current_version == 2
    assert pt.current.claim == "Use REST with HATEOAS."
    assert len(pt.versions) == 2


# ── Events ────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_emits_events(mock_litellm):
    """Deliberation emits start, agent_message, cycle, and complete events."""
    responses = [
        _make_completion_response(_board_turn(
            new_points=[{"claim": "Point A."}],
        )),
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "Ok."}],
        )),
        _make_completion_response(_board_turn(done=True)),
        _make_completion_response(_board_turn(done=True)),
        _make_completion_response(json.dumps({
            "summary": "Summary.",
            "mode_selection": "generative",
            "mode_reasoning": "Creative task.",
            "open_items": [],
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
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
    assert "agent_message" in event_types


# ── converse_with_team ────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_converse_with_team(mock_litellm):
    """converse_with_team wraps deliberate with user_message as task."""
    responses = [
        _make_completion_response(_board_turn(
            new_points=[{"claim": "We chose microservices for scalability."}],
        )),
        _make_completion_response(_board_turn(
            reactions=[{"point_id": 1, "stance": "agree", "reasoning": "Correct."}],
        )),
        _make_completion_response(_board_turn(done=True)),
        _make_completion_response(_board_turn(done=True)),
        _make_completion_response(json.dumps({
            "summary": "Discussion about user question.",
            "mode_selection": "generative",
            "mode_reasoning": "Exploratory.",
            "open_items": [],
        })),
    ]
    mock_litellm.acompletion = AsyncMock(side_effect=responses)

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=10)
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


# ── allowed_modes parameter ───────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_allowed_modes_accepted(mock_litellm):
    """allowed_modes parameter is accepted (single-agent shortcut)."""
    agent_resp = _make_completion_response("I think we should use REST.")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "REST approach chosen.",
        "mode_selection": "generative",
        "mode_reasoning": "Creative task.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(side_effect=[agent_resp, synth_resp])

    historian = MagicMock()
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
        allowed_modes=["generative", "execution"],
    )

    assert isinstance(result, DeliberationResult)
    assert result.mode_selection == "generative"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_allowed_modes_none_still_works(mock_litellm):
    """Not passing allowed_modes (default None) still works."""
    agent_resp = _make_completion_response("Let's decide.")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Decision made.",
        "mode_selection": "decision",
        "mode_reasoning": "Need a choice.",
        "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(side_effect=[agent_resp, synth_resp])

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator,
        agents=agents,
        task="Pick a DB",
        context="",
        historian=historian,
        config=config,
    )

    assert result.mode_selection == "decision"


# ── Token tracking ────────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_deliberate_tracks_tokens(mock_litellm):
    """Token counts are accumulated across all LLM calls."""
    agent_resp = _make_completion_response("Use REST.")
    synth_resp = _make_completion_response(json.dumps({
        "summary": "Done.", "mode_selection": "generative",
        "mode_reasoning": "x", "open_items": [],
    }))
    mock_litellm.acompletion = AsyncMock(side_effect=[agent_resp, synth_resp])

    historian = MagicMock()
    config = DeliberationConfig(max_rounds=6)
    agents = [_make_agent("engineer")]
    moderator = _make_agent("moderator")

    result = await deliberate(
        moderator_agent=moderator, agents=agents,
        task="x", context="", historian=historian, config=config,
    )

    # 2 calls × 50 input + 2 calls × 25 output
    assert result.total_input_tokens == 100
    assert result.total_output_tokens == 50
