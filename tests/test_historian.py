"""Tests for the Historian — RAG briefing, queries, and circular detection."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.agent import AgentResponse
from agentagent.core.historian import Historian
from agentagent.store.models import Decision, DecisionStatus, DiscussionSummary, OpenQuestion


# ── Helpers ───────────────────────────────────────────────────


def _make_repo():
    """Create a mock Repository with all async methods stubbed."""
    repo = MagicMock()
    repo.get_active_decisions = AsyncMock(return_value=[])
    repo.get_open_questions = AsyncMock(return_value=[])
    repo.get_summaries = AsyncMock(return_value=[])
    repo.get_decisions_by_topic = AsyncMock(return_value=[])
    repo.search = MagicMock(return_value=[])
    return repo


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


# ── brief() ───────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_brief_empty_context(mock_litellm):
    """Brief when the knowledge store is empty — should still produce output."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("No prior context. Starting fresh.")
    )
    repo = _make_repo()
    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")

    result = await historian.brief("architecture", "Design the API")
    assert isinstance(result, str)
    assert len(result) > 0
    repo.get_active_decisions.assert_awaited_once_with("p1")
    repo.get_summaries.assert_awaited_once_with("p1")
    repo.get_open_questions.assert_awaited_once_with("p1")


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_brief_with_decisions_and_questions(mock_litellm):
    """Brief incorporates decisions, summaries, and open questions into the prompt."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("Based on prior decisions: use React.")
    )
    repo = _make_repo()
    repo.get_active_decisions.return_value = [
        Decision(
            project_id="p1", topic="Frontend", decision_text="Use React",
            rationale="Team experience", team="arch", round_number=1,
            confidence=0.85, status=DecisionStatus.ACTIVE,
        )
    ]
    repo.get_open_questions.return_value = [
        OpenQuestion(project_id="p1", question="Which state lib?", raised_by="engineer")
    ]
    repo.get_summaries.return_value = [
        DiscussionSummary(
            project_id="p1", team="arch", round_number=1,
            topic="Frontend stack", key_points="Discussed React vs Vue",
            conclusions="React chosen",
        )
    ]
    repo.search.return_value = [{"text": "React was chosen for its ecosystem", "metadata": {}, "distance": 0.1}]

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.brief("frontend", "Build the dashboard")

    assert "React" in result
    # Verify the LLM was called with a prompt containing our context
    call_args = mock_litellm.acompletion.call_args
    prompt = call_args[1]["messages"][1]["content"]
    assert "Frontend" in prompt
    assert "Which state lib?" in prompt


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_brief_survives_search_failure(mock_litellm):
    """Brief still works when semantic search throws."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("Briefing without search context.")
    )
    repo = _make_repo()
    repo.search.side_effect = RuntimeError("chroma unavailable")

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.brief("arch", "Design the API")
    assert isinstance(result, str)
    assert len(result) > 0


# ── query() ───────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_query_with_context(mock_litellm):
    """Query returns an answer synthesized from knowledge store."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("React was chosen because of team experience.")
    )
    repo = _make_repo()
    repo.search.return_value = [
        {"text": "Decision: Use React", "metadata": {"type": "decision"}, "distance": 0.05}
    ]
    repo.get_active_decisions.return_value = [
        Decision(
            project_id="p1", topic="Frontend", decision_text="Use React",
            rationale="Team experience", team="arch", round_number=1,
        )
    ]

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    response = await historian.query("Why did we choose React?")

    assert isinstance(response, AgentResponse)
    assert "React" in response.content


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_query_empty_store(mock_litellm):
    """Query still produces an answer when the store is empty."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("No relevant information available.")
    )
    repo = _make_repo()
    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    response = await historian.query("What is the deployment strategy?")
    assert isinstance(response, AgentResponse)


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_query_survives_search_failure(mock_litellm):
    """Query still works when semantic search throws."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("Unable to find relevant context.")
    )
    repo = _make_repo()
    repo.search.side_effect = RuntimeError("chroma down")

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    response = await historian.query("What is the database?")
    assert isinstance(response, AgentResponse)


# ── check_circular() ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_circular_no_match():
    """No circular discussion when search returns nothing."""
    repo = _make_repo()
    repo.search.return_value = []

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.check_circular("Brand new topic")
    assert result is None


@pytest.mark.asyncio
async def test_check_circular_distant_match():
    """No circular discussion when closest match is too far (distance > 0.3)."""
    repo = _make_repo()
    repo.search.return_value = [{"text": "unrelated", "distance": 0.8, "metadata": {}}]

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.check_circular("Something sort of related")
    assert result is None


@pytest.mark.asyncio
async def test_check_circular_detected():
    """Circular discussion detected when close match found with prior decisions."""
    repo = _make_repo()
    repo.search.return_value = [{"text": "Database selection discussed", "distance": 0.1, "metadata": {}}]
    repo.get_decisions_by_topic.return_value = [
        Decision(
            project_id="p1", topic="Database", decision_text="Use Postgres",
            rationale="Mature and reliable", team="arch", round_number=1,
            status=DecisionStatus.ACTIVE,
        )
    ]

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.check_circular("Choose a database")
    assert result is not None
    assert "Postgres" in result
    assert "ACTIVE" in result


@pytest.mark.asyncio
async def test_check_circular_close_match_but_no_decisions():
    """Close semantic match but no decisions on the topic — not circular."""
    repo = _make_repo()
    repo.search.return_value = [{"text": "Database mentioned", "distance": 0.15, "metadata": {}}]
    repo.get_decisions_by_topic.return_value = []

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.check_circular("Database schema")
    assert result is None


@pytest.mark.asyncio
async def test_check_circular_survives_search_failure():
    """Circular check returns None when search throws."""
    repo = _make_repo()
    repo.search.side_effect = RuntimeError("chroma unavailable")

    historian = Historian(model="gpt-4o", repository=repo, project_id="p1")
    result = await historian.check_circular("Any topic")
    assert result is None
