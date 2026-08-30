import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock
from app.main import app
from app.core.database import get_db


@pytest.mark.asyncio
async def test_health_endpoint_success(client: AsyncClient):
    """Verify /api/v1/health returns 200 with ok status and api_version."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["api_version"] == "v1"
    assert data["database"] == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_db_failure_graceful(client: AsyncClient):
    """Verify /api/v1/health reports degraded status truthfully when database query fails."""
    # Mock a database session that raises an error
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("DB Connection Lost")

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["api_version"] == "v1"
        assert data["database"] == "unavailable"
    finally:
        app.dependency_overrides.clear()
