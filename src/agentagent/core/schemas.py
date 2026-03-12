"""Pydantic response schemas for structured LLM output.

These models validate JSON responses from LLM calls, ensuring type safety
at the boundary between the LLM and application code. Used with
``response_format=JSON_MODE`` to guarantee valid JSON from the model.
"""

from __future__ import annotations

import re
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

T = TypeVar("T", bound=BaseModel)

# Constant passed to litellm.acompletion as ``response_format``
JSON_MODE: dict[str, str] = {"type": "json_object"}


class ComplexityClassification(BaseModel):
    """Result of the fast-track complexity classifier."""

    complexity: Literal["simple", "complex"]


def parse_llm_json(content: str, model: type[T]) -> T:
    """Parse LLM response content as a Pydantic model.

    Handles common LLM quirks: markdown fences, leading/trailing whitespace.
    Raises ``ValidationError`` or ``ValueError`` on failure.
    """
    text = content.strip()
    try:
        return model.model_validate_json(text)
    except (ValidationError, ValueError):
        # Strip markdown code fences and retry
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
            text = text.strip()
        return model.model_validate_json(text)


# ── Stenographer ──────────────────────────────────────────────


class ExtractedDecision(BaseModel):
    """A single decision extracted from a team discussion."""

    topic: str
    decision: str
    rationale: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ExtractedQuestion(BaseModel):
    """An open question extracted from a team discussion."""

    question: str
    raised_by: str
    priority: Literal["critical", "high", "medium", "low"] = "medium"


class StenographerExtraction(BaseModel):
    """Full structured output from the stenographer's analysis of a round."""

    key_points: str
    conclusions: str
    unresolved_items: str = ""
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    open_questions: list[ExtractedQuestion] = Field(default_factory=list)


# ── Generative Mode — Scoring ────────────────────────────────


class AgentScore(BaseModel):
    agent: str
    score: int = Field(ge=0, le=10)
    reasoning: str


class ScoringResponse(BaseModel):
    scores: list[AgentScore]


# ── Evaluative Mode — Review ─────────────────────────────────


class ReviewIssue(BaseModel):
    issue: str
    severity: Literal["critical", "major", "minor"]
    suggestion: str = ""


class ReviewResponse(BaseModel):
    issues: list[ReviewIssue] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    overall_assessment: Literal["pass", "needs_changes", "fail"]


# ── Execution Mode — Decomposition ───────────────────────────


class Subtask(BaseModel):
    assignee: str
    task: str
    dependencies: list[str] = Field(default_factory=list)


class TaskDecomposition(BaseModel):
    subtasks: list[Subtask]


# ── Decision Mode — Options ──────────────────────────────────


class DecisionOption(BaseModel):
    name: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class OptionsResponse(BaseModel):
    options: list[DecisionOption]
    recommendation: str
    reasoning: str


# ── Moderator ────────────────────────────────────────────────


class ChallengeResponse(BaseModel):
    agree: bool = True
    suggested_mode: str = ""
    reason: str = ""


class CompletenessResponse(BaseModel):
    complete: bool
    reasoning: str
    missing: list[str] = Field(default_factory=list)


# ── Forum Gate ───────────────────────────────────────────────


class GateEvaluation(BaseModel):
    result: Literal["approved", "approved_with_notes", "returned"]
    notes: str = ""
    missing: list[str] = Field(default_factory=list)


# ── Forum — Message Classification ──────────────────────────


class MessageClassification(BaseModel):
    """Audience classification for a user message during execution."""

    audience: Literal["current_step", "workflow"]
    summary: str = ""
