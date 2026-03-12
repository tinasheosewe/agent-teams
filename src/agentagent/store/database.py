"""Async SQLite database setup."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
        """Create all tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def session(self) -> AsyncSession:
        """Return a new async session."""
        return self._session_factory()

    async def close(self) -> None:
        await self._engine.dispose()
