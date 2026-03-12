"""SQLAlchemy models for the Knowledge Store."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class DecisionStatus(str, enum.Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVERTED = "reverted"


class ArtifactStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    NEEDS_REWORK = "needs_rework"
    FINAL = "final"


class Priority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QuestionStatus(str, enum.Enum):
    OPEN = "open"
    ANSWERED = "answered"
    DEFERRED = "deferred"


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text)
    config_name: Mapped[str] = mapped_column(String(256))
    config_path: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="created")
    mode: Mapped[str] = mapped_column(String(32), default="interactive")
    total_input_tokens: Mapped[int] = mapped_column(default=0)
    total_output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    topic: Mapped[str] = mapped_column(String(256))
    decision_text: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    team: Mapped[str] = mapped_column(String(128))
    round_number: Mapped[int]
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus), default=DecisionStatus.ACTIVE
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("decisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    supersedes: Mapped[Decision | None] = relationship(
        "Decision", remote_side=[id], foreign_keys=[supersedes_id]
    )

    __table_args__ = (
        Index("ix_decisions_project_topic", "project_id", "topic"),
        Index("ix_decisions_project_status", "project_id", "status"),
    )


class DiscussionSummary(Base):
    __tablename__ = "discussion_summaries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    team: Mapped[str] = mapped_column(String(128))
    round_number: Mapped[int]
    topic: Mapped[str] = mapped_column(String(256))
    key_points: Mapped[str] = mapped_column(Text)
    conclusions: Mapped[str] = mapped_column(Text)
    unresolved_items: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("ix_summaries_project_team", "project_id", "team"),)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    team: Mapped[str] = mapped_column(String(128))
    round_number: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    artifact_type: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    team: Mapped[str] = mapped_column(String(128))
    status: Mapped[ArtifactStatus] = mapped_column(
        Enum(ArtifactStatus), default=ArtifactStatus.DRAFT
    )
    linked_decision_ids: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("ix_artifacts_project_type", "project_id", "artifact_type"),)

    @property
    def linked_decision_id_list(self) -> list[str]:
        """Return linked decision IDs as a typed list."""
        if not self.linked_decision_ids:
            return []
        return [x.strip() for x in self.linked_decision_ids.split(",") if x.strip()]


class OpenQuestion(Base):
    __tablename__ = "open_questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text)
    raised_by: Mapped[str] = mapped_column(String(128))
    assigned_to: Mapped[str] = mapped_column(String(128), default="")
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.MEDIUM)
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus), default=QuestionStatus.OPEN
    )
    answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
