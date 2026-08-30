import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from app.core.config import settings

logger = logging.getLogger("nctb.services.llm.circuit_breaker")


class ProviderState(str, Enum):
    AVAILABLE = "AVAILABLE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"


def parse_retry_after(error_msg: str, default_wait: float = 60.0) -> float:
    """
    Parses wait duration in formats:
    - 'try again in 16.665s' -> 16.665
    - 'try again in 2m25s' / 'try again in 2m25.4s' -> 145.4
    - 'try again in 1h20m30s' -> 4830
    - 'try again in 34m' -> 2040
    """
    clean = error_msg.lower()

    # Check for composite h/m/s e.g. 1h20m30s or 2m25s
    match_composite = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+\.?\d*)s)?", clean)
    if match_composite and any(match_composite.groups()):
        h = float(match_composite.group(1) or 0)
        m = float(match_composite.group(2) or 0)
        s = float(match_composite.group(3) or 0)
        total = h * 3600.0 + m * 60.0 + s
        if total > 0:
            return total

    # Check for simple minutes e.g. "34m" or "34 minutes"
    match_m = re.search(r"try again in (\d+\.?\d*)\s*(?:m|min|minutes)", clean)
    if match_m:
        return float(match_m.group(1)) * 60.0

    # Check for simple seconds e.g. "16.7s" or "16.7 seconds"
    match_s = re.search(r"try again in (\d+\.?\d*)\s*(?:s|sec|seconds)", clean)
    if match_s:
        return float(match_s.group(1))

    return default_wait


@dataclass
class ProviderCircuitStatus:
    provider_name: str
    state: ProviderState = ProviderState.AVAILABLE
    unavailable_until: Optional[float] = None
    reason: Optional[str] = None
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None

    def is_available(self, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.time()
        if self.state == ProviderState.TEMPORARILY_UNAVAILABLE:
            if self.unavailable_until and now >= self.unavailable_until:
                # Automatic recovery
                logger.info(
                    f"Circuit breaker for provider '{self.provider_name}' recovered automatically "
                    f"after cooldown period ({self.reason or 'cooldown completed'})."
                )
                self.state = ProviderState.AVAILABLE
                self.unavailable_until = None
                self.reason = None
                self.failure_count = 0
                return True
            return False
        return True

    def mark_unavailable(self, duration_seconds: float, reason: str):
        now = time.time()
        safety_buffer = getattr(settings, "LLM_CIRCUIT_RECOVERY_SAFETY_SECONDS", 15.0) or 15.0
        total_cooldown = max(1.0, duration_seconds + safety_buffer)

        self.state = ProviderState.TEMPORARILY_UNAVAILABLE
        self.unavailable_until = now + total_cooldown
        self.reason = reason
        self.failure_count += 1
        self.last_failure_time = now
        until_iso = datetime.fromtimestamp(self.unavailable_until, tz=timezone.utc).isoformat()
        logger.warning(
            f"Circuit opened for provider '{self.provider_name}': {reason}. "
            f"Unavailable for {total_cooldown:.1f}s until {until_iso} (failure #{self.failure_count})."
        )

    def mark_success(self):
        now = time.time()
        if self.state == ProviderState.TEMPORARILY_UNAVAILABLE:
            logger.info(f"Provider '{self.provider_name}' succeeded. Resetting circuit state to AVAILABLE.")
        self.state = ProviderState.AVAILABLE
        self.unavailable_until = None
        self.reason = None
        self.failure_count = 0
        self.success_count += 1
        self.last_success_time = now


class ProviderCircuitBreaker:
    """
    Ephemeral in-memory circuit breaker for LLM providers.
    Tracks availability, quotas, and automatic recovery periods per provider.
    Never persisted to database.
    """

    def __init__(self):
        self._providers: Dict[str, ProviderCircuitStatus] = {}

    def _get_or_create(self, provider_name: str) -> ProviderCircuitStatus:
        key = provider_name.lower().strip()
        if key not in self._providers:
            self._providers[key] = ProviderCircuitStatus(provider_name=key)
        return self._providers[key]

    def is_available(self, provider_name: str, current_time: Optional[float] = None) -> bool:
        return self._get_or_create(provider_name).is_available(current_time)

    def mark_unavailable(self, provider_name: str, duration_seconds: float, reason: str):
        self._get_or_create(provider_name).mark_unavailable(duration_seconds, reason)

    def mark_success(self, provider_name: str):
        self._get_or_create(provider_name).mark_success()

    def get_status(self, provider_name: str) -> Dict[str, Any]:
        status = self._get_or_create(provider_name)
        return {
            "provider": status.provider_name,
            "state": status.state.value,
            "is_available": status.is_available(),
            "unavailable_until": status.unavailable_until,
            "reason": status.reason,
            "failure_count": status.failure_count,
            "success_count": status.success_count,
        }

    def reset(self):
        """Reset all circuit breaker states (primarily for test isolation)."""
        self._providers.clear()


# Global in-memory circuit breaker instance
provider_circuit_breaker = ProviderCircuitBreaker()
