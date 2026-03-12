"""Tests for the Stenographer — transcript recording, LLM extraction, and fallbacks."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.stenographer import Stenographer
from agentagent.store.models import (
    Decision,
    DecisionStatus,
    DiscussionSummary,
    OpenQuestion,
    Transcript,
)


# ── Helpers ───────────────────────────────────────────────────


def _make_repo():
    """Create a mock Repository with all async write methods stubbed."""
    repo = MagicMock()
    # save_transcript returns a Transcript
    async def _save_transcript(t):
        t.id = "tr-1"
        return t
    repo.save_transcript = AsyncMock(side_effect=_save_transcript)

    # save_summary returns a DiscussionSummary
    async def _save_summary(s):
        s.id = "sum-1"
        return s
    repo.save_summary = AsyncMock(side_effect=_save_summary)

    # save_decision returns a Decision
    async def _save_decision(d):
        d.id = "dec-1"
        return d
    repo.save_decision = AsyncMock(side_effect=_save_decision)

    # save_question returns an OpenQuestion
    async def _save_question(q):
        q.id = "q-1"
        return q
    repo.save_question = AsyncMock(side_effect=_save_question)

    return repo


def _make_completion_response(content: str):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


GOOD_EXTRACTION = json.dumps({
    "key_points": "Discussed API structure and auth approach",
    "conclusions": "REST API with JWT authentication",
    "unresolved_items": "Rate limiting strategy TBD",
    "decisions": [
        {
            "topic": "Authentication",
            "decision": "Use JWT tokens",
            "rationale": "Stateless and scalable",
            "confidence": 0.9,
        }
    ],
    "open_questions": [
        {
            "question": "What rate limiting strategy to use?",
            "raised_by": "engineer",
            "priority": "medium",
        }
    ],
})


# ── record_round() full flow ─────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_record_round_full_flow(mock_litellm):
    """Full happy path: transcript saved, LLM extracts decisions + questions, all saved."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(GOOD_EXTRACTION)
    )
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    summary = await steno.record_round(
        team="backend",
        round_number=1,
        transcript_text="Engineer: Let's use JWT for auth.\nArchitect: Agreed, it's stateless.",
        topic="API Authentication",
    )

    # Transcript was saved
    repo.save_transcript.assert_awaited_once()
    saved_transcript = repo.save_transcript.call_args[0][0]
    assert saved_transcript.team == "backend"
    assert saved_transcript.round_number == 1
    assert "JWT" in saved_transcript.content

    # Summary was saved with extracted fields
    repo.save_summary.assert_awaited_once()
    saved_summary = repo.save_summary.call_args[0][0]
    assert "API structure" in saved_summary.key_points
    assert "JWT" in saved_summary.conclusions

    # Decision was saved
    repo.save_decision.assert_awaited_once()
    saved_dec = repo.save_decision.call_args[0][0]
    assert saved_dec.topic == "Authentication"
    assert saved_dec.decision_text == "Use JWT tokens"
    assert saved_dec.confidence == 0.9
    assert saved_dec.status == DecisionStatus.ACTIVE

    # Open question was saved
    repo.save_question.assert_awaited_once()
    saved_q = repo.save_question.call_args[0][0]
    assert "rate limiting" in saved_q.question.lower()

    # Returns a DiscussionSummary
    assert isinstance(summary, DiscussionSummary)


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_record_round_multiple_decisions(mock_litellm):
    """Extracts and saves multiple decisions from a single round."""
    extraction = json.dumps({
        "key_points": "Multiple decisions made",
        "conclusions": "Tech stack finalized",
        "unresolved_items": "",
        "decisions": [
            {"topic": "Frontend", "decision": "Use React", "rationale": "Ecosystem", "confidence": 0.85},
            {"topic": "Backend", "decision": "Use FastAPI", "rationale": "Performance", "confidence": 0.9},
        ],
        "open_questions": [],
    })
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(extraction)
    )
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    await steno.record_round(team="arch", round_number=2, transcript_text="...", topic="Tech stack")

    assert repo.save_decision.await_count == 2
    topics = [repo.save_decision.call_args_list[i][0][0].topic for i in range(2)]
    assert "Frontend" in topics
    assert "Backend" in topics


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_record_round_no_decisions_or_questions(mock_litellm):
    """Round with no decisions or questions — only transcript and summary saved."""
    extraction = json.dumps({
        "key_points": "Brainstorming session",
        "conclusions": "No conclusions yet",
        "unresolved_items": "Everything",
        "decisions": [],
        "open_questions": [],
    })
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(extraction)
    )
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    await steno.record_round(team="design", round_number=1, transcript_text="...", topic="Ideation")

    repo.save_transcript.assert_awaited_once()
    repo.save_summary.assert_awaited_once()
    repo.save_decision.assert_not_awaited()
    repo.save_question.assert_not_awaited()


# ── Fallback on parse failure ─────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_record_round_llm_garbage(mock_litellm):
    """When LLM returns unparseable output, transcript is saved and summary uses raw content."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("This is not JSON at all, just a rambling response.")
    )
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    summary = await steno.record_round(
        team="backend", round_number=3, transcript_text="...", topic="API design"
    )

    # Transcript always saved regardless
    repo.save_transcript.assert_awaited_once()

    # Summary saved with raw content as key_points
    repo.save_summary.assert_awaited_once()
    saved_summary = repo.save_summary.call_args[0][0]
    assert "rambling" in saved_summary.key_points
    assert saved_summary.conclusions == ""

    # No decisions or questions saved (graceful degradation)
    repo.save_decision.assert_not_awaited()
    repo.save_question.assert_not_awaited()


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_record_round_markdown_fenced_json(mock_litellm):
    """LLM wraps JSON in markdown fences — still parsed correctly."""
    fenced = f"```json\n{GOOD_EXTRACTION}\n```"
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response(fenced)
    )
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    await steno.record_round(team="backend", round_number=1, transcript_text="...", topic="Auth")

    # Decision should still be extracted despite markdown fencing
    repo.save_decision.assert_awaited_once()
    assert repo.save_decision.call_args[0][0].decision_text == "Use JWT tokens"


# ── estimate_token_count() ────────────────────────────────────


def test_estimate_token_count():
    from agentagent.core.agent import Message
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    messages = [
        Message(role="user", content="a" * 400),
        Message(role="assistant", content="b" * 200),
    ]
    estimate = steno.estimate_token_count(messages)
    assert estimate == 150  # (400 + 200) // 4


def test_estimate_token_count_empty():
    from agentagent.core.agent import Message
    repo = _make_repo()
    steno = Stenographer(model="gpt-4o-mini", repository=repo, project_id="p1")

    assert steno.estimate_token_count([]) == 0
