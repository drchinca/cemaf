"""
Accurate token counting using tiktoken.

Provides precise token counts for OpenAI models.
Falls back to heuristic for unknown models.

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation.
Tiktoken import happens at runtime to avoid hard dependency.
"""

from __future__ import annotations

from functools import lru_cache


class TiktokenEstimator:
    """
    Accurate token estimator using tiktoken.

    Caches encodings for performance.
    Falls back to character heuristic if tiktoken not available.

    Usage:
        estimator = TiktokenEstimator(model="gpt-4")
        tokens = estimator.estimate("Hello, world!")
    """

    # Model to encoding mapping
    MODEL_ENCODINGS = {
        "gpt-4": "cl100k_base",
        "gpt-4-turbo": "cl100k_base",
        "gpt-4o": "o200k_base",
        "gpt-4o-mini": "o200k_base",
        "gpt-3.5-turbo": "cl100k_base",
        "text-embedding-ada-002": "cl100k_base",
        "text-embedding-3-small": "cl100k_base",
        "text-embedding-3-large": "cl100k_base",
        # Claude models use different tokenizer, fallback to heuristic
    }

    def __init__(
        self,
        model: str = "gpt-4",
        fallback_chars_per_token: float = 4.0,
    ) -> None:
        self._model = model
        self._fallback_ratio = fallback_chars_per_token
        self._encoding: tiktoken.Encoding | None = None  # noqa: F821
        self._tiktoken_available = False

        # Try to initialize tiktoken
        self._init_tiktoken()

    def _init_tiktoken(self) -> None:
        """Initialize tiktoken encoding if available."""
        try:
            import tiktoken

            encoding_name = self.MODEL_ENCODINGS.get(self._model)
            if encoding_name:
                self._encoding = tiktoken.get_encoding(encoding_name)
            else:
                # Try model-based encoding
                try:
                    self._encoding = tiktoken.encoding_for_model(self._model)
                except KeyError:
                    # Unknown model, use cl100k_base as default
                    self._encoding = tiktoken.get_encoding("cl100k_base")

            self._tiktoken_available = True
        except ImportError:
            # tiktoken not installed
            self._tiktoken_available = False

    def estimate(self, text: str) -> int:
        """
        Estimate token count for text.

        Uses tiktoken if available, falls back to character heuristic.
        """
        if self._tiktoken_available and self._encoding:
            return len(self._encoding.encode(text))

        # Fallback: character-based heuristic
        return max(1, int(len(text) / self._fallback_ratio))

    def estimate_messages(
        self,
        messages: list[dict],
        include_overhead: bool = True,
    ) -> int:
        """
        Estimate tokens for a list of messages.

        Includes message format overhead (role, separators).
        """
        total = 0

        for msg in messages:
            if include_overhead:
                # OpenAI format overhead: ~4 tokens per message
                total += 4

            content = msg.get("content", "")
            if content:
                total += self.estimate(content)

            # Tool calls in message
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    total += self.estimate(func.get("name", ""))
                    total += self.estimate(str(func.get("arguments", "")))

        if include_overhead:
            # Final assistant reply priming
            total += 3

        return total

    @property
    def is_accurate(self) -> bool:
        """Whether using accurate tiktoken counting."""
        return self._tiktoken_available

    @property
    def model(self) -> str:
        """Model this estimator is configured for."""
        return self._model


@lru_cache(maxsize=8)
def get_estimator(model: str = "gpt-4") -> TiktokenEstimator:
    """Get a cached estimator for a model."""
    return TiktokenEstimator(model=model)
