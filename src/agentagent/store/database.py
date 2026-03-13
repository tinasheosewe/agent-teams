"""Async SQLite database setup."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentagent.store.models import Base

DEFAULT_DB_PATH = Path("data/agentagent.db")


class Database:
    """Manages the async SQLite connection and session factory."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def initialize(self) -> None:
        """Create all tables and apply lightweight schema upgrades."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await self._ensure_projects_schema(conn)

    async def _ensure_projects_schema(self, conn: AsyncConnection) -> None:
        """Backfill missing columns for older SQLite project databases."""
        result = await conn.execute(text("PRAGMA table_info(projects)"))
        existing_columns = {row[1] for row in result.fetchall()}

        missing_column_sql = {
            "config_path": "ALTER TABLE projects ADD COLUMN config_path VARCHAR(512) DEFAULT ''",
            "status": "ALTER TABLE projects ADD COLUMN status VARCHAR(32) DEFAULT 'created'",
            "mode": "ALTER TABLE projects ADD COLUMN mode VARCHAR(32) DEFAULT 'interactive'",
            "total_input_tokens": "ALTER TABLE projects ADD COLUMN total_input_tokens INTEGER DEFAULT 0",
            "total_output_tokens": "ALTER TABLE projects ADD COLUMN total_output_tokens INTEGER DEFAULT 0",
            "estimated_cost": "ALTER TABLE projects ADD COLUMN estimated_cost FLOAT DEFAULT 0.0",
        }

        for column_name, ddl in missing_column_sql.items():
            if column_name not in existing_columns:
                await conn.execute(text(ddl))

    def session(self) -> AsyncSession:
        """Return a new async session."""
        return self._session_factory()

    async def close(self) -> None:
        await self._engine.dispose()
