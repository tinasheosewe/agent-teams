"""Tests for Pydantic LLM response schemas and parse_llm_json utility."""

import pytest
from pydantic import ValidationError

from agentagent.core.schemas import (
    DiscussionSynthesis,
    GateEvaluation,
    OptionsResponse,
    ReflectionSynthesis,
    ReviewResponse,
    ScoringResponse,
    SpiralCheck,
    StenographerExtraction,
    TaskDecomposition,
    json_schema_format,
    parse_llm_json,
)


# ── parse_llm_json ───────────────────────────────────────────


def test_parse_clean_json():
    raw = '{"key_points": "good code", "conclusions": "ship it"}'
    result = parse_llm_json(raw, StenographerExtraction)
    assert result.key_points == "good code"
    assert result.conclusions == "ship it"
    assert result.decisions == []


def test_parse_markdown_fenced_json():
    raw = '```json\n{"key_points": "clean", "conclusions": "done"}\n```'
    result = parse_llm_json(raw, StenographerExtraction)
    assert result.key_points == "clean"


def test_parse_invalid_json_raises():
    with pytest.raises((ValidationError, ValueError)):
        parse_llm_json("not json at all", StenographerExtraction)


def test_parse_missing_required_field():
    raw = '{"key_points": "only one field"}'
    with pytest.raises(ValidationError):
        parse_llm_json(raw, StenographerExtraction)


# ── ScoringResponse ──────────────────────────────────────────


def test_scoring_response_valid():
    raw = '{"scores": [{"agent": "engineer", "score": 8, "reasoning": "solid"}]}'
    data = parse_llm_json(raw, ScoringResponse)
    assert len(data.scores) == 1
    assert data.scores[0].agent == "engineer"
    assert data.scores[0].score == 8


def test_scoring_response_score_out_of_range():
    raw = '{"scores": [{"agent": "x", "score": 15, "reasoning": "oops"}]}'
    with pytest.raises(ValidationError):
        parse_llm_json(raw, ScoringResponse)


# ── ReviewResponse ────────────────────────────────────────────


def test_review_response_valid():
    raw = (
        '{"issues": [{"issue": "no tests", "severity": "major"}], '
        '"strengths": ["fast"], "overall_assessment": "needs_changes"}'
    )
    data = parse_llm_json(raw, ReviewResponse)
    assert data.overall_assessment == "needs_changes"
    assert data.issues[0].severity == "major"


def test_review_response_invalid_severity():
    raw = (
        '{"issues": [{"issue": "bad", "severity": "extreme"}], '
        '"strengths": [], "overall_assessment": "pass"}'
    )
    with pytest.raises(ValidationError):
        parse_llm_json(raw, ReviewResponse)


# ── TaskDecomposition ─────────────────────────────────────────


def test_task_decomposition():
    raw = '{"subtasks": [{"assignee": "dev", "task": "build API"}]}'
    data = parse_llm_json(raw, TaskDecomposition)
    assert data.subtasks[0].assignee == "dev"
    assert data.subtasks[0].dependencies == []


# ── OptionsResponse ───────────────────────────────────────────


def test_options_response():
    raw = (
        '{"options": [{"name": "Postgres", "pros": ["mature"], "cons": ["complex"]}], '
        '"recommendation": "Postgres", "reasoning": "best fit"}'
    )
    data = parse_llm_json(raw, OptionsResponse)
    assert data.options[0].name == "Postgres"
    assert data.recommendation == "Postgres"


# ── Discussion schemas ────────────────────────────────────────


def test_spiral_check_circular():
    raw = '{"is_circular": true, "reason": "Same argument", "redirect_topic": "Focus"}'
    data = parse_llm_json(raw, SpiralCheck)
    assert data.is_circular is True
    assert data.redirect_topic == "Focus"


def test_spiral_check_not_circular():
    raw = '{"is_circular": false, "reason": "Making progress"}'
    data = parse_llm_json(raw, SpiralCheck)
    assert data.is_circular is False
    assert data.redirect_topic is None


def test_discussion_synthesis():
    raw = '{"summary": "Use REST", "mode_selection": "execution", "mode_reasoning": "Build task", "open_items": []}'
    data = parse_llm_json(raw, DiscussionSynthesis)
    assert data.mode_selection == "execution"
    assert data.mode_reasoning == "Build task"


def test_reflection_synthesis_accept():
    raw = '{"summary": "Looks good", "verdict": "accept", "revision_guidance": "", "confidence": 0.95}'
    data = parse_llm_json(raw, ReflectionSynthesis)
    assert data.verdict == "accept"
    assert data.confidence == 0.95


def test_reflection_synthesis_revise():
    raw = '{"summary": "Needs work", "verdict": "revise", "revision_guidance": "Fix errors", "confidence": 0.3}'
    data = parse_llm_json(raw, ReflectionSynthesis)
    assert data.verdict == "revise"
    assert data.revision_guidance == "Fix errors"


def test_json_schema_format_structure():
    schema = SpiralCheck.model_json_schema()
    fmt = json_schema_format("TestSchema", schema)
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "TestSchema"
    assert "schema" in fmt["json_schema"]


# ── GateEvaluation ────────────────────────────────────────────


def test_gate_approved():
    raw = '{"result": "approved", "notes": "looks good"}'
    data = parse_llm_json(raw, GateEvaluation)
    assert data.result == "approved"


def test_gate_invalid_result():
    raw = '{"result": "rejected", "notes": "bad"}'
    with pytest.raises(ValidationError):
        parse_llm_json(raw, GateEvaluation)
