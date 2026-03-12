"""Repository — read/write interface to the Knowledge Store.

Stenographer writes. Historian reads. No other agent touches the store directly.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, update

from agentagent.store.database import Database
from agentagent.store.models import (
    Artifact,
    ArtifactStatus,
    Decision,
    DecisionStatus,
    DiscussionSummary,
    OpenQuestion,
    QuestionStatus,
    Transcript,
)
from agentagent.store.vector import VectorStore


class Repository:
    """Unified read/write interface to the Knowledge Store."""

    def __init__(self, db: Database, vector: VectorStore) -> None:
        self._db = db
        self._vector = vector

    # ── Decisions ──────────────────────────────────────────────

    async def save_decision(self, decision: Decision) -> Decision:
        async with self._db.session() as session:
            session.add(decision)
            await session.commit()
            await session.refresh(decision)
        self._vector.add(
            doc_id=f"decision:{decision.id}",
            text=f"{decision.topic}: {decision.decision_text}. Rationale: {decision.rationale}",
            metadata={
                "project_id": decision.project_id,
                "type": "decision",
                "team": decision.team,
                "status": decision.status.value,
            },
        )
        return decision

    async def supersede_decision(
        self, old_id: str, new_decision: Decision
    ) -> Decision:
        """Mark old decision as superseded and save the new one."""
        async with self._db.session() as session:
            await session.execute(
                update(Decision)
                .where(Decision.id == old_id)
                .values(status=DecisionStatus.SUPERSEDED)
            )
            new_decision.supersedes_id = old_id
            session.add(new_decision)
            await session.commit()
            await session.refresh(new_decision)
        self._vector.add(
            doc_id=f"decision:{old_id}",
            text=f"[SUPERSEDED] {old_id}",
            metadata={"project_id": new_decision.project_id, "type": "decision", "status": "superseded"},
        )
        self._vector.add(
            doc_id=f"decision:{new_decision.id}",
            text=f"{new_decision.topic}: {new_decision.decision_text}. Rationale: {new_decision.rationale}",
            metadata={
                "project_id": new_decision.project_id,
                "type": "decision",
                "team": new_decision.team,
                "status": "active",
            },
        )
        return new_decision

    async def get_active_decisions(self, project_id: str) -> Sequence[Decision]:
        async with self._db.session() as session:
            result = await session.execute(
                select(Decision).where(
                    Decision.project_id == project_id,
                    Decision.status == DecisionStatus.ACTIVE,
                )
            )
            return result.scalars().all()

    async def get_decisions_by_topic(
        self, project_id: str, topic: str
    ) -> Sequence[Decision]:
        async with self._db.session() as session:
            result = await session.execute(
                select(Decision)
                .where(Decision.project_id == project_id, Decision.topic == topic)
                .order_by(Decision.created_at)
            )
            return result.scalars().all()

    # ── Discussion Summaries ──────────────────────────────────

    async def save_summary(self, summary: DiscussionSummary) -> DiscussionSummary:
        async with self._db.session() as session:
            session.add(summary)
            await session.commit()
            await session.refresh(summary)
        self._vector.add(
            doc_id=f"summary:{summary.id}",
            text=f"[{summary.team} R{summary.round_number}] {summary.topic}: {summary.key_points}. Conclusions: {summary.conclusions}",
            metadata={
                "project_id": summary.project_id,
                "type": "summary",
                "team": summary.team,
            },
        )
        return summary

    async def get_summaries(
        self, project_id: str, team: str | None = None
    ) -> Sequence[DiscussionSummary]:
        async with self._db.session() as session:
            stmt = select(DiscussionSummary).where(
                DiscussionSummary.project_id == project_id
            )
            if team:
                stmt = stmt.where(DiscussionSummary.team == team)
            stmt = stmt.order_by(DiscussionSummary.created_at)
            result = await session.execute(stmt)
            return result.scalars().all()

    # ── Transcripts ───────────────────────────────────────────

    async def save_transcript(self, transcript: Transcript) -> Transcript:
        async with self._db.session() as session:
            session.add(transcript)
            await session.commit()
            await session.refresh(transcript)
        return transcript

    async def get_transcript(
        self, project_id: str, team: str, round_number: int
    ) -> Transcript | None:
        async with self._db.session() as session:
            result = await session.execute(
                select(Transcript).where(
                    Transcript.project_id == project_id,
                    Transcript.team == team,
                    Transcript.round_number == round_number,
                )
            )
            return result.scalar_one_or_none()

    # ── Artifacts ─────────────────────────────────────────────

    async def save_artifact(self, artifact: Artifact) -> Artifact:
        async with self._db.session() as session:
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
        self._vector.add(
            doc_id=f"artifact:{artifact.id}",
            text=f"[{artifact.artifact_type}] {artifact.name}: {artifact.content[:500]}",
            metadata={
                "project_id": artifact.project_id,
                "type": "artifact",
                "artifact_type": artifact.artifact_type,
                "team": artifact.team,
            },
        )
        return artifact

    async def get_artifacts(
        self, project_id: str, artifact_type: str | None = None
    ) -> Sequence[Artifact]:
        async with self._db.session() as session:
            stmt = select(Artifact).where(Artifact.project_id == project_id)
            if artifact_type:
                stmt = stmt.where(Artifact.artifact_type == artifact_type)
            stmt = stmt.order_by(Artifact.created_at)
            result = await session.execute(stmt)
            return result.scalars().all()

    async def flag_artifacts_for_rework(
        self, project_id: str, decision_id: str
    ) -> list[str]:
        """Flag artifacts linked to a superseded decision as needing rework."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Artifact).where(Artifact.project_id == project_id)
            )
            artifacts = result.scalars().all()
            flagged: list[str] = []
            for art in artifacts:
                linked = art.linked_decision_ids.split(",") if art.linked_decision_ids else []
                if decision_id in linked:
                    art.status = ArtifactStatus.NEEDS_REWORK
                    session.add(art)
                    flagged.append(art.id)
            await session.commit()
            return flagged

    # ── Open Questions ────────────────────────────────────────

    async def save_question(self, question: OpenQuestion) -> OpenQuestion:
        async with self._db.session() as session:
            session.add(question)
            await session.commit()
            await session.refresh(question)
        return question

    async def get_open_questions(self, project_id: str) -> Sequence[OpenQuestion]:
        async with self._db.session() as session:
            result = await session.execute(
                select(OpenQuestion).where(
                    OpenQuestion.project_id == project_id,
                    OpenQuestion.status == QuestionStatus.OPEN,
                )
            )
            return result.scalars().all()

    async def answer_question(self, question_id: str, answer: str) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(OpenQuestion)
                .where(OpenQuestion.id == question_id)
                .values(answer=answer, status=QuestionStatus.ANSWERED)
            )
            await session.commit()

    # ── Semantic Search (for Historian) ───────────────────────

    def search(
        self, project_id: str, query: str, n_results: int = 5
    ) -> list[dict]:
        """Semantic search across all knowledge for a project."""
        return self._vector.query(
            text=query,
            n_results=n_results,
            where={"project_id": project_id},
        )
