from typing import Optional


class LLMProviderException(ValueError):
    """Base exception for all LLM provider errors (inherits from ValueError for broad compatibility)."""
    pass


class LLMNotConfiguredError(LLMProviderException):
    """Raised when an LLM provider's API key is missing or blank."""
    pass


class LLMQuotaExhaustedError(LLMProviderException):
    """Raised when provider daily or monthly account quota is exhausted."""
    def __init__(self, message: str, retry_after_seconds: float = 300.0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMRateLimitError(LLMProviderException):
    """Raised when provider TPM or RPM rate limits are exceeded."""
    def __init__(self, message: str, retry_after_seconds: float = 60.0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMRequestTooLargeError(LLMProviderException):
    """Raised when prompt context exceeds token window / TPM limits."""
    pass


class LLMTimeoutError(LLMProviderException, TimeoutError):
    """Raised when LLM API request times out."""
    pass


class LLMUnavailableError(LLMProviderException):
    """Raised when all configured LLM providers are temporarily unavailable."""
    pass


class LLMProviderError(LLMProviderException):
    """Raised on provider 5xx or unclassified service errors."""
    pass


class LLMSchemaValidationError(LLMProviderException):
    """Raised when LLM output cannot be parsed or fails Pydantic schema validation."""
    pass
