import pytest
from sqlalchemy import text
from app.core.database import init_db, get_db


@pytest.mark.asyncio
async def test_database_initialization():
    """Verify init_db establishes connection successfully."""
    ok = await init_db()
    assert ok is True


@pytest.mark.asyncio
async def test_get_db_session():
    """Verify get_db generator yields active session."""
    async for session in get_db():
        result = await session.execute(text("SELECT 1 AS alive"))
        assert result.scalar() == 1
