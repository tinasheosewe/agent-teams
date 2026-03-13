"""Pydantic models for domain configuration."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class InteractionMode(str, Enum):
    GENERATIVE = "generative"
    EVALUATIVE = "evaluative"
    EXECUTION = "execution"
    DECISION = "decision"


class Complexity(str, Enum):
    LIGHT = "light"
    STANDARD = "standard"
    THOROUGH = "thorough"


class ThinkingDepth(str, Enum):
    """How deeply agents should deliberate before and after execution."""

    PERSPECTIVE_ONLY = "perspective_only"  # OPEN round only, no probing
    FULL = "full"                         # Full deliberation with tension probing


class GateCriteria(BaseModel):
    """Acceptance criteria for a workflow gate."""

    description: str = ""
    automated_checks: list[str] = Field(default_factory=list)
    review_required: bool = True


class ExpertConfig(BaseModel):
    """Configuration for a single domain expert agent."""

    role: str
    persona: str
    model: str = "gpt-4o"
    tools: list[str] = Field(default_factory=list)


class TeamConfig(BaseModel):
    """Configuration for a team of agents."""

    name: str
    purpose: str
    experts: list[ExpertConfig]
    preferred_modes: list[InteractionMode] = Field(
        default_factory=lambda: list(InteractionMode)
    )
    moderator_model: str = "gpt-4o"
    max_rounds: int = 10
    enable_deliberation: bool = False
    thinking_depth: ThinkingDepth = ThinkingDepth.FULL
    max_deliberation_cycles: int = 3


class WorkflowStep(BaseModel):
    """A single step in the workflow pipeline."""

    step: str
    gate: str
    output: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    parallel_with: list[str] = Field(default_factory=list)
    on_fail: str | None = None
    gate_criteria: GateCriteria = Field(default_factory=GateCriteria)


class CompanyConfig(BaseModel):
    """Top-level configuration for an agent company."""

    name: str
    description: str = ""
    teams: list[TeamConfig]
    workflow: list[WorkflowStep]
    artifact_types: list[str] = Field(default_factory=list)
    default_model: str = "gpt-4o"
    historian_model: str = "gpt-4o"
    stenographer_model: str = "gpt-4o-mini"
    complexity: Complexity = Complexity.STANDARD


def load_config(path: str | Path) -> CompanyConfig:
    """Load and validate a company configuration from a YAML file."""
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    return CompanyConfig(**raw["company"])
