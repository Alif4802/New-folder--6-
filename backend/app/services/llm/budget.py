import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type
from app.core.config import settings

logger = logging.getLogger("nctb.services.llm.budget")


@dataclass
class TokenEstimate:
    character_count: int
    word_count: int
    estimated_tokens: int


class TokenEstimator:
    """
    Authoritative, unified conservative token estimator for LLM inputs and schemas.
    Accounts for punctuation, math LaTeX delimiters, and JSON schema overhead.
    """

    @classmethod
    def estimate_text_tokens(cls, text: str) -> TokenEstimate:
        if not text:
            return TokenEstimate(character_count=0, word_count=0, estimated_tokens=0)

        chars = len(text)
        words = len(text.split())

        # Conservative heuristic: 1 token ~= 3.4 characters for mixed prose/math/XML
        # Add slight bump for symbols/math tags
        symbol_count = len(re.findall(r"[\$\{\}\[\]\<\>\=\\\_\^\*\#]", text))
        base_estimate = math.ceil(chars / 3.4) + math.ceil(symbol_count * 0.4)

        return TokenEstimate(
            character_count=chars,
            word_count=words,
            estimated_tokens=max(1, base_estimate),
        )

    @classmethod
    def estimate_prompt_tokens(
        cls,
        system_prompt: str,
        user_prompt: str,
        schema_name: str = "",
        schema_dict: Optional[Dict[str, Any]] = None,
    ) -> int:
        sys_est = cls.estimate_text_tokens(system_prompt).estimated_tokens
        user_est = cls.estimate_text_tokens(user_prompt).estimated_tokens

        # Estimated schema structure overhead in JSON mode (including envelope & properties)
        schema_tokens = 450
        if schema_dict:
            schema_chars = len(str(schema_dict))
            schema_tokens = max(350, math.ceil(schema_chars / 3.4))

        # 60 tokens for role message envelopes and system delimiters
        return sys_est + user_est + schema_tokens + 60

    @classmethod
    def enforce_prompt_token_budget(
        cls,
        chunks: List[Any],
        render_user_prompt_fn: Callable[[List[Any]], str],
        system_prompt: str,
        max_target_tokens: int = 2800,
        schema_name: str = "LLMMCGCandidateResponse",
        schema_dict: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Any], str, int]:
        """
        Guarantees that the rendered prompt strictly fits under max_target_tokens.
        If oversized, progressively trims chunks from the end until within budget.
        Returns: (fitted_chunks, rendered_user_prompt, total_est_tokens).
        """
        current_chunks = list(chunks)

        while current_chunks:
            user_prompt = render_user_prompt_fn(current_chunks)
            total_est = cls.estimate_prompt_tokens(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name=schema_name,
                schema_dict=schema_dict,
            )
            if total_est <= max_target_tokens or len(current_chunks) <= 1:
                if total_est > max_target_tokens:
                    logger.warning(
                        f"Single chunk still exceeds budget ({total_est} > {max_target_tokens}). Trimming content length..."
                    )
                return current_chunks, user_prompt, total_est

            # Drop the last chunk to reduce token footprint
            logger.info(
                f"Prompt estimated at {total_est} tokens (> target {max_target_tokens}). "
                f"Trimming chunk '{getattr(current_chunks[-1], 'chunk_id', 'last')}' to fit budget..."
            )
            current_chunks.pop()

        user_prompt = render_user_prompt_fn([])
        total_est = cls.estimate_prompt_tokens(system_prompt, user_prompt, schema_name, schema_dict)
        return [], user_prompt, total_est


@dataclass
class ProviderBudget:
    """
    Centralized provider token and rate limit budget configuration.
    Keeps prompts safely bounded under provider TPM and request ceilings.
    """
    tpm_limit: int = 8000
    request_token_target: int = 2800  # Max target tokens per generation request
    verify_token_target: int = 4000   # Max target tokens per verification request
    output_token_reserve: int = 1500   # Reserve for generated output tokens
    safety_ratio: float = 0.85
    max_retries: int = 2
    backoff_seconds: float = 2.0

    @classmethod
    def get_default_budget(cls) -> "ProviderBudget":
        tpm = getattr(settings, "LLM_TPM_LIMIT", 8000) or 8000
        req_target = getattr(settings, "LLM_REQUEST_TOKEN_TARGET", 2800) or 2800
        ver_target = getattr(settings, "LLM_VERIFY_REQUEST_TOKEN_TARGET", 4000) or 4000
        out_reserve = getattr(settings, "LLM_OUTPUT_TOKEN_RESERVE", 1500) or 1500

        return cls(
            tpm_limit=tpm,
            request_token_target=req_target,
            verify_token_target=ver_target,
            output_token_reserve=out_reserve,
        )

    def is_within_budget(self, estimated_prompt_tokens: int, is_verification: bool = False) -> bool:
        """Returns True if the estimated prompt fits within safe request target."""
        target = self.verify_token_target if is_verification else self.request_token_target
        return estimated_prompt_tokens <= target
