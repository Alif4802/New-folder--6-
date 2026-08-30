import logging
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.health import HealthResponse

logger = logging.getLogger("nctb.api.health")
router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="System Health Check")
async def get_health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """
    Check application and database health.
    Returns 200 with status='ok' when database is operational,
    or status='degraded' with database='unavailable' if database query fails.
    """
    api_version = "v1"
    db_status = "unavailable"
    app_status = "degraded"

    try:
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            db_status = "ok"
            app_status = "ok"
    except Exception as exc:
        logger.warning(f"Health check database query failed: {exc}")
        db_status = "unavailable"
        app_status = "degraded"

    return HealthResponse(
        status=app_status,
        api_version=api_version,
        database=db_status,
    )
