import pytest
from pydantic import BaseModel, Field
from typing import List

from app.services.llm.groq_provider import GroqProvider
from app.schemas.llm_mcq import LLMMCGCandidateResponse


class SimpleSampleSchema(BaseModel):
    summary: str
    items: List[str] = Field(default_factory=list)


def test_groq_provider_missing_key_behavior():
    """Verifies that GroqProvider cleanly reports is_configured=False and raises LLM_NOT_CONFIGURED."""
    provider = GroqProvider(api_key="")
    assert provider.is_configured is False

    provider_none = GroqProvider(api_key=None)
    # If settings.GROQ_API_KEY is empty, is_configured must be False
    if not provider_none.api_key:
        assert provider_none.is_configured is False


@pytest.mark.asyncio
async def test_groq_provider_unconfigured_raises_error():
    provider = GroqProvider(api_key="")
    with pytest.raises(ValueError) as exc:
        await provider.generate_structured(
            system_instruction="System",
            user_prompt="User",
            response_schema=SimpleSampleSchema,
        )
    assert "LLM_NOT_CONFIGURED" in str(exc.value)


def test_groq_json_schema_generation():
    """Verifies that Pydantic models generate valid JSON schema for Groq structured output."""
    schema = LLMMCGCandidateResponse.model_json_schema()
    assert "properties" in schema
    assert "questions" in schema["properties"]
    assert "insufficient_context" in schema["properties"]
