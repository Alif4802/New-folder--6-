import logging
import time
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.circuit_breaker import ProviderCircuitBreaker, provider_circuit_breaker
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.services.llm.exceptions import (
    LLMNotConfiguredError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMRequestTooLargeError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMProviderError,
    LLMSchemaValidationError,
    LLMProviderException,
)

logger = logging.getLogger("nctb.services.llm.router")

T = TypeVar("T", bound=BaseModel)


class LLMProviderRouter(LLMProvider):
    """
    Resilient provider router with transparent failover and in-memory circuit breaker.
    Primary: Groq (openai/gpt-oss-120b)
    Fallback: OpenRouter (openai/gpt-oss-120b:free)
    """

    def __init__(
        self,
        primary: Optional[LLMProvider] = None,
        fallback: Optional[LLMProvider] = None,
        circuit_breaker: Optional[ProviderCircuitBreaker] = None,
    ):
        self.primary = primary or GroqProvider()
        self.fallback = fallback or OpenRouterProvider()
        self.circuit_breaker = circuit_breaker or provider_circuit_breaker

        # Telemetry metrics
        self.total_calls = 0
        self.primary_calls = 0
        self.fallback_calls = 0
        self.failovers_triggered = 0

    @property
    def is_configured(self) -> bool:
        primary_conf = getattr(self.primary, "is_configured", True)
        fallback_conf = getattr(self.fallback, "is_configured", False) if self.fallback else False
        return primary_conf or fallback_conf

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        self.total_calls += 1
        primary_name = "groq"
        fallback_name = "openrouter"

        primary_available = self.circuit_breaker.is_available(primary_name)
        primary_configured = getattr(self.primary, "is_configured", True)

        fallback_configured = getattr(self.fallback, "is_configured", False) if self.fallback else False
        fallback_available = self.circuit_breaker.is_available(fallback_name) if self.fallback else False

        # Case 1: Primary is available & configured -> Attempt Primary First
        if primary_available and primary_configured:
            try:
                self.primary_calls += 1
                result = await self.primary.generate_structured(
                    system_instruction=system_instruction,
                    user_prompt=user_prompt,
                    response_schema=response_schema,
                )
                self.circuit_breaker.mark_success(primary_name)
                return result

            except (LLMQuotaExhaustedError, LLMRateLimitError, LLMTimeoutError, LLMProviderError, TimeoutError, ConnectionError) as prov_err:
                # Primary encountered a temporary infrastructure/rate/quota failure -> Open circuit & Failover
                self.failovers_triggered += 1
                cooldown = 60.0
                if hasattr(prov_err, "retry_after_seconds"):
                    cooldown = getattr(prov_err, "retry_after_seconds")

                self.circuit_breaker.mark_unavailable(primary_name, cooldown, str(prov_err))

                if not fallback_configured:
                    logger.warning(f"Primary '{primary_name}' failed ({prov_err}), but fallback '{fallback_name}' is not configured.")
                    raise LLMUnavailableError(
                        "LLM_TEMPORARILY_UNAVAILABLE: Primary LLM service is temporarily busy and backup provider is not configured."
                    ) from prov_err

                if not fallback_available:
                    logger.warning(f"Primary '{primary_name}' failed and fallback '{fallback_name}' circuit is also OPEN.")
                    raise LLMUnavailableError(
                        "LLM_TEMPORARILY_UNAVAILABLE: All LLM generation services are temporarily unavailable."
                    ) from prov_err

                logger.info(
                    f"Primary provider '{primary_name}' unavailable ({prov_err}). "
                    f"Failing over to backup provider '{fallback_name}'..."
                )

                try:
                    self.fallback_calls += 1
                    result = await self.fallback.generate_structured(
                        system_instruction=system_instruction,
                        user_prompt=user_prompt,
                        response_schema=response_schema,
                    )
                    self.circuit_breaker.mark_success(fallback_name)
                    return result
                except Exception as fb_err:
                    self.circuit_breaker.mark_unavailable(fallback_name, 60.0, str(fb_err))
                    logger.error(f"Fallback provider '{fallback_name}' also failed: {fb_err}")
                    raise LLMUnavailableError(
                        "LLM_TEMPORARILY_UNAVAILABLE: All LLM generation services are currently unavailable. Please retry shortly."
                    ) from fb_err

            except (LLMSchemaValidationError, LLMRequestTooLargeError, ValueError) as app_err:
                # Do NOT failover on semantic validation or prompt errors - fail fast
                raise

        # Case 2: Primary is unavailable (Circuit OPEN) -> Direct Route to Fallback
        if fallback_configured and fallback_available:
            logger.info(f"Primary '{primary_name}' circuit is OPEN. Routing directly to fallback '{fallback_name}'...")
            try:
                self.fallback_calls += 1
                result = await self.fallback.generate_structured(
                    system_instruction=system_instruction,
                    user_prompt=user_prompt,
                    response_schema=response_schema,
                )
                self.circuit_breaker.mark_success(fallback_name)
                return result
            except Exception as fb_err:
                self.circuit_breaker.mark_unavailable(fallback_name, 60.0, str(fb_err))
                logger.error(f"Fallback provider '{fallback_name}' failed: {fb_err}")
                raise LLMUnavailableError(
                    "LLM_TEMPORARILY_UNAVAILABLE: All LLM generation services are currently unavailable. Please retry shortly."
                ) from fb_err

        # Case 3: Neither provider is available or configured
        if not primary_configured and not fallback_configured:
            raise LLMNotConfiguredError("LLM_NOT_CONFIGURED: No LLM provider API keys are configured.")

        raise LLMUnavailableError("LLM_TEMPORARILY_UNAVAILABLE: All LLM providers are currently unavailable. Please retry shortly.")
