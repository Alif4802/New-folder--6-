import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.budget import TokenEstimator

logger = logging.getLogger("nctb.services.llm.openrouter")

T = TypeVar("T", bound=BaseModel)


def _sanitize_error_message(msg: str) -> str:
    """Strip external URLs, authorization tokens, and internal IDs from error messages."""
    clean = re.sub(r"https?://\S+", "", msg)
    clean = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", clean, flags=re.I)
    clean = re.sub(r"sk-or-[a-zA-Z0-9_\-]+", "[REDACTED]", clean)
    clean = re.sub(r"org_[a-zA-Z0-9]+", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter API client for fallback LLM structured completion.
    Uses OpenAI-compatible chat completions endpoint with model 'openai/gpt-oss-120b:free'.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        base_url: str = "https://openrouter.ai/api/v1",
    ):
        self.api_key = api_key if api_key is not None else settings.OPENROUTER_API_KEY
        self.model = model or settings.OPENROUTER_MODEL or "openai/gpt-oss-120b:free"
        self.timeout = timeout or settings.LLM_PROVIDER_ATTEMPT_TIMEOUT_SECONDS or 30.0
        self.base_url = base_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        if not self.is_configured:
            raise ValueError(
                "LLM_NOT_CONFIGURED: OpenRouter API key is not configured. "
                "Please set OPENROUTER_API_KEY in backend .env."
            )

        # Estimate prompt tokens for logging
        est_tokens = TokenEstimator.estimate_prompt_tokens(
            system_prompt=system_instruction,
            user_prompt=user_prompt,
            schema_name=response_schema.__name__,
            schema_dict=response_schema.model_json_schema(),
        )
        logger.info(f"OpenRouter generation request: model='{self.model}', estimated_prompt_tokens={est_tokens}")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://nctb-intelligence.local",
            "X-Title": "NCTB Intelligence Demo",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ]

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": response_schema.model_json_schema(),
                },
            },
        }

        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as te:
                logger.error(f"OpenRouter request timed out after {self.timeout}s: {te}")
                raise TimeoutError(f"LLM_TIMEOUT: OpenRouter request timed out after {self.timeout}s.") from te
            except httpx.NetworkError as ne:
                clean_err = _sanitize_error_message(str(ne))
                logger.error(f"OpenRouter network connection error: {clean_err}")
                raise ConnectionError(f"LLM_PROVIDER_ERROR: OpenRouter network error: {clean_err}") from ne

            # If json_schema response_format is unsupported by specific free tier endpoint, fallback to json_object
            if response.status_code == 400 and "response_format" in response.text.lower():
                logger.warning("OpenRouter json_schema format rejected. Retrying with type=json_object...")
                payload["response_format"] = {"type": "json_object"}
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except Exception as retry_err:
                    clean_msg = _sanitize_error_message(str(retry_err))
                    raise RuntimeError(f"LLM_PROVIDER_ERROR: OpenRouter retry failed: {clean_msg}") from retry_err

            if response.status_code == 429:
                clean_err = _sanitize_error_message(response.text)
                logger.warning(f"OpenRouter rate limit / quota exceeded (429): {clean_err}")
                if "quota" in clean_err.lower() or "limit" in clean_err.lower():
                    raise RuntimeError(f"LLM_QUOTA_EXHAUSTED: OpenRouter rate/quota limit reached.")
                raise RuntimeError(f"LLM_RATE_LIMIT: OpenRouter rate limit encountered.")

            if response.status_code == 413 or (response.status_code == 400 and "context" in response.text.lower()):
                clean_err = _sanitize_error_message(response.text)
                logger.warning(f"OpenRouter request too large: {clean_err}")
                raise RuntimeError(f"LLM_REQUEST_TOO_LARGE: OpenRouter token budget exceeded.")

            if response.status_code >= 500:
                clean_err = _sanitize_error_message(response.text)
                logger.error(f"OpenRouter 5xx server error ({response.status_code}): {clean_err}")
                raise RuntimeError(f"LLM_PROVIDER_ERROR: OpenRouter service unavailable (HTTP {response.status_code}).")

            if response.status_code != 200:
                clean_err = _sanitize_error_message(response.text)
                logger.error(f"OpenRouter returned status {response.status_code}: {clean_err}")
                raise RuntimeError(f"LLM_PROVIDER_ERROR: OpenRouter returned status {response.status_code}.")

            try:
                res_json = response.json()
            except Exception as parse_err:
                logger.error(f"Failed to parse OpenRouter response envelope as JSON: {parse_err}")
                raise ValueError("LLM_SCHEMA_VALIDATION_ERROR: OpenRouter returned invalid response envelope.") from parse_err

            choices = res_json.get("choices", [])
            if not choices:
                raise ValueError("LLM_SCHEMA_VALIDATION_ERROR: OpenRouter returned 0 choices.")

            content = choices[0].get("message", {}).get("content", "")
            if not content or not content.strip():
                raise ValueError("LLM_SCHEMA_VALIDATION_ERROR: OpenRouter returned empty message content.")

            # Parse JSON content and validate against Pydantic schema
            try:
                raw_data = json.loads(content)
            except json.JSONDecodeError as jde:
                logger.error(f"Failed to decode OpenRouter inner content as JSON: {jde}\nContent: {content[:300]}")
                raise ValueError("LLM_SCHEMA_VALIDATION_ERROR: Model output did not contain valid JSON.") from jde

            try:
                validated = response_schema.model_validate(raw_data)
                logger.info(f"OpenRouter structured generation succeeded for '{response_schema.__name__}'.")
                return validated
            except Exception as val_err:
                logger.error(f"Schema validation error on OpenRouter response: {val_err}")
                raise ValueError(f"LLM_SCHEMA_VALIDATION_ERROR: Model output failed schema validation: {val_err}") from val_err
