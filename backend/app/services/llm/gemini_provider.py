import asyncio
import logging
from typing import Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.config import settings
from app.services.llm.base import LLMProvider

logger = logging.getLogger("nctb.services.llm.gemini")

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(LLMProvider):
    """
    Google Gemini Provider using official google-genai SDK and structured JSON output.
    Configured specifically for Gemini 3.7 Flash without legacy sampling parameters.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        thinking_level: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL
        self.thinking_level = thinking_level or settings.LLM_THINKING_LEVEL
        self.max_output_tokens = max_output_tokens or settings.LLM_MAX_OUTPUT_TOKENS
        self.timeout_seconds = timeout_seconds or settings.LLM_TIMEOUT_SECONDS

        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if not self.api_key:
            raise ValueError("LLM_NOT_CONFIGURED: Google Gemini API key is missing or not configured.")
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        client = self._get_client()

        # Build thinking config if supported
        thinking_config = None
        if self.thinking_level and self.thinking_level.lower() != "off":
            try:
                thinking_config = types.ThinkingConfig(thinking_level=self.thinking_level.lower())
            except Exception as e:
                logger.warning(f"Could not initialize ThinkingConfig with level {self.thinking_level}: {e}")

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            max_output_tokens=self.max_output_tokens,
            thinking_config=thinking_config,
            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
        )

        try:
            logger.info(f"Calling Gemini API model={self.model} (structured output)...")
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=config,
            )
        except asyncio.TimeoutError:
            logger.error(f"Gemini API request timed out after {self.timeout_seconds}s")
            raise TimeoutError(f"LLM_TIMEOUT: Gemini call exceeded {self.timeout_seconds} seconds timeout.")
        except APIError as e:
            logger.error(f"Gemini API error ({e.code}): {e.message}")
            raise RuntimeError(f"LLM_PROVIDER_ERROR: Gemini API returned error: {e.message}")
        except Exception as e:
            logger.error(f"Gemini generation exception: {e}")
            raise RuntimeError(f"LLM_PROVIDER_ERROR: {str(e)}")

        # Handle parsed structured output
        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, response_schema):
                return response.parsed
            try:
                return response_schema.model_validate(response.parsed)
            except ValidationError as ve:
                logger.warning(f"Failed to validate response.parsed directly: {ve}")

        raw_text = response.text or ""
        if not raw_text.strip():
            raise ValueError("INVALID_LLM_OUTPUT: Gemini returned empty content.")

        try:
            return response_schema.model_validate_json(raw_text)
        except ValidationError as ve:
            logger.error(f"Schema validation error on Gemini output: {ve}")
            raise ValueError(f"INVALID_LLM_OUTPUT: Model response failed schema validation: {ve}")
