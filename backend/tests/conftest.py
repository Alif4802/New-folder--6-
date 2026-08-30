import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from app.core.config import settings
from app.core.database import Base, get_db, bootstrap_default_curriculum
from app.main import app as fastapi_app
from app.services.storage import init_storage_directories


@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def isolated_test_environment(tmp_path: Path):
    """
    Guarantees that tests run against an isolated temporary SQLite database and
    isolated storage root, preventing any modification to data/nctb_intelligence.db.
    """
    test_db_file = tmp_path / "test_isolated.db"
    test_storage_dir = tmp_path / "test_storage"

    # Configure isolated paths in settings
    original_db_url = settings.DATABASE_URL
    original_storage_root = settings.STORAGE_ROOT

    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db_file.as_posix()}"
    settings.STORAGE_ROOT = test_storage_dir

    # Initialize storage directories in isolated location
    init_storage_directories()

    # Create isolated test engine
    test_engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
    )
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    # Initialize schema and bootstrap default curriculum
    async with test_engine.begin() as conn:
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        await bootstrap_default_curriculum(session)

    # Override the FastAPI dependency
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    yield

    # Teardown
    fastapi_app.dependency_overrides.clear()
    await test_engine.dispose()
    settings.DATABASE_URL = original_db_url
    settings.STORAGE_ROOT = original_storage_root


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an asynchronous HTTP test client."""
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a direct asynchronous database session for unit tests."""
    override = fastapi_app.dependency_overrides.get(get_db)
    if override:
        async for s in override():
            yield s

