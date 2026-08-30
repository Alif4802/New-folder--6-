import logging
from typing import Optional
from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.services.llm.mock_provider import MockProvider
from app.services.llm.router import LLMProviderRouter

logger = logging.getLogger("nctb.services.llm.factory")


def get_llm_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """
    Factory function returning the configured LLMProvider instance.
    - 'mock': MockProvider (automated tests only)
    - 'groq': GroqProvider directly
    - 'openrouter': OpenRouterProvider directly
    - 'gemini': GeminiProvider directly
    - default ('router' or 'groq'): LLMProviderRouter (Groq primary + OpenRouter fallback)
    """
    active = (provider_name or settings.LLM_PROVIDER).lower().strip()

    if active == "mock":
        return MockProvider()
    elif active == "openrouter":
        return OpenRouterProvider()
    elif active == "gemini":
        return GeminiProvider()
    elif active == "groq_direct":
        return GroqProvider()
    else:
        # Default runtime: Resilient Router with Groq Primary + OpenRouter Fallback
        return LLMProviderRouter()
