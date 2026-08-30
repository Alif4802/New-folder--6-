from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMResponse(BaseModel):
    raw_content: str
    structured_data: Dict[str, Any]
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    model_name: str
    duration_ms: float


class LLMProvider(ABC):
    """Abstract interface for structured LLM completion."""

    @abstractmethod
    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        """
        Generate a structured response strictly conforming to the given Pydantic schema.
        Raises appropriate exceptions on configuration, network, timeout, or parsing failure.
        """
        pass
