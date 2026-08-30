import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel
from groq import AsyncGroq, APIError, APITimeoutError, RateLimitError, BadRequestError

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.budget import TokenEstimator
from app.services.llm.exceptions import (
    LLMNotConfiguredError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMRequestTooLargeError,
    LLMTimeoutError,
    LLMProviderError,
    LLMSchemaValidationError,
)

logger = logging.getLogger("nctb.services.llm.groq")

T = TypeVar("T", bound=BaseModel)


def _sanitize_error_message(msg: str) -> str:
    """Strip external URLs, billing references, and internal IDs from error messages."""
    clean = re.sub(r"https?://\S+", "", msg)
    clean = re.sub(r"org_[a-zA-Z0-9]+", "", clean)
    clean = re.sub(r"gsk_[a-zA-Z0-9]+", "[REDACTED]", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


class GroqProvider(LLMProvider):
    """
    Official Groq Python SDK provider implementation with token budget estimation,
    JSON Schema structured output, and rate limit error sanitation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
    ):
        self.api_key = api_key if api_key is not None else (settings.GROQ_API_KEY or settings.LLM_API_KEY)
        self.model = model or settings.GROQ_MODEL or settings.LLM_MODEL or "openai/gpt-oss-120b"
        self.timeout = timeout or settings.LLM_PROVIDER_ATTEMPT_TIMEOUT_SECONDS or 30.0
        self.reasoning_effort = reasoning_effort or settings.LLM_REASONING_EFFORT

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
            raise LLMNotConfiguredError("LLM_NOT_CONFIGURED: Groq API key is not configured. Please set GROQ_API_KEY in backend .env.")

        # Estimate prompt tokens for diagnostics
        est_tokens = TokenEstimator.estimate_prompt_tokens(
            system_prompt=system_instruction,
            user_prompt=user_prompt,
            schema_name=response_schema.__name__,
            schema_dict=response_schema.model_json_schema(),
        )
        logger.info(f"Groq generation request: model='{self.model}', estimated_prompt_tokens={est_tokens}")

        client = AsyncGroq(api_key=self.api_key, timeout=self.timeout)

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "schema": response_schema.model_json_schema(),
            },
        }

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "response_format": response_format,
        }

        if self.reasoning_effort and self.reasoning_effort.lower() in ["low", "medium", "high"]:
            kwargs["reasoning_effort"] = self.reasoning_effort.lower()

        max_auto_retry_seconds = getattr(settings, "LLM_MAX_AUTO_RETRY_WAIT_SECONDS", 8.0)

        try:
            max_attempts = 2
            for attempt in range(max_attempts):
                try:
                    try:
                        response = await client.chat.completions.create(**kwargs)
                    except Exception as e:
                        # If reasoning_effort is unsupported for the specific model, retry without it
                        if "reasoning_effort" in kwargs and "reasoning_effort" in str(e):
                            logger.warning(f"Model '{self.model}' does not accept reasoning_effort parameter. Retrying without it.")
                            kwargs.pop("reasoning_effort")
                            response = await client.chat.completions.create(**kwargs)
                        else:
                            raise

                    content = response.choices[0].message.content
                    if not content or not content.strip():
                        raise LLMSchemaValidationError("LLM_SCHEMA_VALIDATION_ERROR: Groq returned empty response content.")

                    raw_json = json.loads(content)
                    validated = response_schema.model_validate(raw_json)
                    logger.info(f"Groq structured generation succeeded for '{response_schema.__name__}'.")
                    return validated

                except RateLimitError as rle:
                    clean_msg = _sanitize_error_message(str(rle))
                    logger.warning(f"Groq rate limit encountered: {clean_msg}")

                    # Parse wait duration accurately (seconds, minutes, or composite)
                    from app.services.llm.circuit_breaker import parse_retry_after
                    wait_sec = parse_retry_after(str(rle), default_wait=60.0)

                    # Check if daily token/request quota is exhausted
                    is_daily_quota = "tokens per day" in clean_msg.lower() or "tpd" in clean_msg.lower()

                    if is_daily_quota or wait_sec > max_auto_retry_seconds:
                        # Do NOT wait minutes or long periods. Fail immediately to trigger circuit breaker failover!
                        logger.warning(
                            f"Groq wait time ({wait_sec:.1f}s) exceeds auto-retry limit ({max_auto_retry_seconds}s) "
                            f"or quota exhausted. Failing fast for fallback..."
                        )
                        raise LLMQuotaExhaustedError(
                            f"LLM_QUOTA_EXHAUSTED: Groq quota/rate limit reached. Wait required: {wait_sec:.1f}s.",
                            retry_after_seconds=max(wait_sec, 60.0),
                        ) from rle

                    if attempt < max_attempts - 1:
                        logger.info(f"RateLimit on Groq within tolerance ({wait_sec:.1f}s <= {max_auto_retry_seconds}s). Sleeping before retry ({attempt + 1}/{max_attempts})...")
                        await asyncio.sleep(wait_sec)
                        continue

                    raise LLMRateLimitError(
                        f"LLM_RATE_LIMIT: Groq rate limit exceeded after retry.",
                        retry_after_seconds=max(wait_sec, 30.0),
                    ) from rle

        except BadRequestError as bre:
            clean_msg = _sanitize_error_message(str(bre))
            logger.warning(f"Groq bad request / size limit: {clean_msg}")
            if "too large" in clean_msg.lower() or "tokens" in clean_msg.lower() or "413" in str(bre):
                raise LLMRequestTooLargeError("LLM_REQUEST_TOO_LARGE: Request exceeded provider token budget.") from bre
            raise LLMProviderError(f"LLM_PROVIDER_ERROR: Invalid generation request: {clean_msg}") from bre

        except APITimeoutError as te:
            logger.error(f"Groq API call timed out after {self.timeout}s: {te}")
            raise LLMTimeoutError(f"LLM_TIMEOUT: Groq request timed out after {self.timeout}s.") from te

        except APIError as ae:
            clean_msg = _sanitize_error_message(str(ae))
            logger.error(f"Groq API returned error ({ae.status_code}): {clean_msg}")
            if ae.status_code == 413 or "too large" in clean_msg.lower():
                raise LLMRequestTooLargeError("LLM_REQUEST_TOO_LARGE: Request size exceeded provider limits.") from ae
            raise LLMProviderError(f"LLM_PROVIDER_ERROR: Provider returned status {ae.status_code}.") from ae

        except json.JSONDecodeError as jde:
            logger.error(f"Failed to parse Groq response as JSON: {jde}")
            raise LLMSchemaValidationError("LLM_SCHEMA_VALIDATION_ERROR: Model did not return valid structured output.") from jde

        except (LLMNotConfiguredError, LLMQuotaExhaustedError, LLMRateLimitError, LLMRequestTooLargeError, LLMTimeoutError, LLMSchemaValidationError, LLMProviderError):
            raise

        except Exception as ex:
            clean_msg = _sanitize_error_message(str(ex))
            logger.error(f"Unexpected error in GroqProvider: {clean_msg}")
            raise LLMProviderError(f"LLM_PROVIDER_ERROR: {clean_msg}") from ex
