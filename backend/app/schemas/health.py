from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Typed schema for the health verification endpoint."""
    status: str = Field(..., description="Overall system status ('ok' or 'degraded')")
    api_version: str = Field(..., description="Active API version")
    database: str = Field(..., description="Database connectivity status ('ok' or 'unavailable')")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "api_version": "v1",
                "database": "ok"
            }
        }
    }
