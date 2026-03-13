"""Tests for the Knowledge Store."""

import sqlite3

import pytest
from sqlalchemy import text

from agentagent.store.database import Database
from agentagent.store.models import (
    Artifact,
    ArtifactStatus,
    Decision,
    DecisionStatus,
    DiscussionSummary,
    OpenQuestion,
)
from agentagent.store.repository import Repository
from agentagent.store.vector import VectorStore


@pytest.fixture
async def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.initialize()
    vector = VectorStore(persist_dir=str(tmp_path / "chroma"))
    yield Repository(db, vector)
    await db.close()


@pytest.mark.asyncio
async def test_save_and_get_decision(repo):
    d = Decision(
        project_id="proj1",
        topic="Tech Stack",
        decision_text="Use React + FastAPI",
        rationale="Best for our team's experience",
        team="architecture",
        round_number=1,
        confidence=0.9,
    )
    saved = await repo.save_decision(d)
    assert saved.id

    decisions = await repo.get_active_decisions("proj1")
    assert len(decisions) == 1
    assert decisions[0].topic == "Tech Stack"


@pytest.mark.asyncio
async def test_supersede_decision(repo):
    d1 = Decision(
        project_id="proj1",
        topic="Database",
        decision_text="Use PostgreSQL",
        rationale="Relational data",
        team="architecture",
        round_number=1,
    )
    saved1 = await repo.save_decision(d1)

    d2 = Decision(
        project_id="proj1",
        topic="Database",
        decision_text="Use SQLite",
        rationale="Simpler for MVP",
        team="architecture",
        round_number=3,
    )
    saved2 = await repo.supersede_decision(saved1.id, d2)
    assert saved2.supersedes_id == saved1.id

    active = await repo.get_active_decisions("proj1")
    assert len(active) == 1
    assert active[0].decision_text == "Use SQLite"


@pytest.mark.asyncio
async def test_save_and_get_summary(repo):
    s = DiscussionSummary(
        project_id="proj1",
        team="management",
        round_number=1,
        topic="Vision",
        key_points="Target premium dog food market",
        conclusions="Focus on subscription model",
    )
    saved = await repo.save_summary(s)
    assert saved.id

    summaries = await repo.get_summaries("proj1", team="management")
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_save_and_get_artifact(repo):
    a = Artifact(
        project_id="proj1",
        artifact_type="prd",
        name="product_prd",
        content="# PRD\n\n## Overview\n...",
        team="product",
    )
    saved = await repo.save_artifact(a)
    assert saved.id

    artifacts = await repo.get_artifacts("proj1", artifact_type="prd")
    assert len(artifacts) == 1


@pytest.mark.asyncio
async def test_flag_artifacts_for_rework(repo):
    d = Decision(
        project_id="proj1",
        topic="Stack",
        decision_text="Use Vue",
        rationale="Simple",
        team="arch",
        round_number=1,
    )
    saved_d = await repo.save_decision(d)

    a = Artifact(
        project_id="proj1",
        artifact_type="tech_spec",
        name="spec",
        content="Use Vue...",
        team="arch",
        linked_decision_ids=saved_d.id,
    )
    await repo.save_artifact(a)

    flagged = await repo.flag_artifacts_for_rework("proj1", saved_d.id)
    assert len(flagged) == 1

    artifacts = await repo.get_artifacts("proj1")
    assert artifacts[0].status == ArtifactStatus.NEEDS_REWORK


@pytest.mark.asyncio
async def test_semantic_search(repo):
    d = Decision(
        project_id="proj1",
        topic="Payment Provider",
        decision_text="Use Stripe for payments",
        rationale="Best API documentation and developer experience",
        team="architecture",
        round_number=2,
    )
    await repo.save_decision(d)

    results = repo.search("proj1", "payment processing")
    assert len(results) > 0


@pytest.mark.asyncio
async def test_open_questions(repo):
    q = OpenQuestion(
        project_id="proj1",
        question="Do we need user authentication?",
        raised_by="product_manager",
        priority="high",
    )
    saved = await repo.save_question(q)
    assert saved.id

    questions = await repo.get_open_questions("proj1")
    assert len(questions) == 1

    await repo.answer_question(saved.id, "Yes, OAuth2 with Google")
    questions = await repo.get_open_questions("proj1")
    assert len(questions) == 0


@pytest.mark.asyncio
async def test_database_initialize_upgrades_legacy_projects_table(tmp_path):
    db_path = tmp_path / "legacy.db"

    # Simulate a pre-migration schema that lacks newer project columns.
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE projects (
            id VARCHAR(32) PRIMARY KEY,
            prompt TEXT NOT NULL,
            config_name VARCHAR(256) NOT NULL,
            created_at DATETIME
        )
        """
    )
    con.commit()
    con.close()

    db = Database(db_path)
    await db.initialize()

    async with db.session() as session:
        result = await session.execute(text("PRAGMA table_info(projects)"))
        columns = {row[1] for row in result.fetchall()}

    await db.close()

    assert "mode" in columns
    assert "status" in columns
    assert "total_input_tokens" in columns
