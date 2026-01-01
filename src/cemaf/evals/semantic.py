"""
Semantic similarity evaluator - Uses embeddings to compare outputs.

More robust than exact match for:
- Paraphrased content
- Different wording, same meaning
- Partial matches
"""

import math
from typing import Any

from cemaf.core.types import JSON
from cemaf.evals.protocols import (
    BaseEvaluator,
    EvalConfig,
    EvalMetric,
    EvalResult,
)
from cemaf.retrieval.protocols import EmbeddingProvider


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(a) != len(b):
        raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")

    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


class SemanticSimilarityEvaluator(BaseEvaluator):
    """
    Evaluates semantic similarity using embeddings.

    Compares the meaning of output to expected, not exact text.

    Usage:
        evaluator = SemanticSimilarityEvaluator(
            embedding_provider=my_embeddings,
            threshold=0.8,
        )
        result = await evaluator.evaluate(
            output="The sky is blue",
            expected="Blue is the color of the sky"
        )
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        similarity_threshold: float = 0.8,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config, name="SemanticSimilarity")
        self._embedder = embedding_provider
        self._threshold = similarity_threshold

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.SEMANTIC_SIMILARITY

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Evaluate semantic similarity."""
        if expected is None:
            return self._make_result(0.0, "No expected value for comparison")

        out_str = str(output)
        exp_str = str(expected)

        # Handle empty strings
        if not out_str.strip() and not exp_str.strip():
            return self._make_result(1.0, "Both empty")
        if not out_str.strip() or not exp_str.strip():
            return self._make_result(0.0, "One value is empty")

        # Get embeddings
        out_embedding = await self._embedder.embed(out_str)
        exp_embedding = await self._embedder.embed(exp_str)

        # Calculate similarity
        similarity = cosine_similarity(out_embedding, exp_embedding)

        # Normalize to 0-1 (cosine can be negative)
        score = (similarity + 1) / 2

        return self._make_result(
            score=score,
            reason=f"Cosine similarity: {similarity:.3f} (threshold: {self._threshold})",
            expected=exp_str[:100] + "..." if len(exp_str) > 100 else exp_str,
            actual=out_str[:100] + "..." if len(out_str) > 100 else out_str,
        )


class MultiReferenceSemanticEvaluator(BaseEvaluator):
    """
    Semantic similarity against multiple reference answers.

    Passes if output is similar to ANY of the references.
    Useful when there are multiple correct answers.
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        similarity_threshold: float = 0.8,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config, name="MultiReferenceSemanticSimilarity")
        self._embedder = embedding_provider
        self._threshold = similarity_threshold

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.SEMANTIC_SIMILARITY

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Evaluate against multiple references."""
        if expected is None:
            return self._make_result(0.0, "No expected values for comparison")

        # Handle single or multiple expected values
        if isinstance(expected, str):
            references = [expected]
        elif isinstance(expected, (list, tuple)):
            references = [str(r) for r in expected]
        else:
            references = [str(expected)]

        out_str = str(output)
        out_embedding = await self._embedder.embed(out_str)

        # Compare against all references
        similarities: list[tuple[str, float]] = []

        for ref in references:
            ref_embedding = await self._embedder.embed(ref)
            sim = cosine_similarity(out_embedding, ref_embedding)
            similarities.append((ref, sim))

        # Get best match
        best_ref, best_sim = max(similarities, key=lambda x: x[1])
        score = (best_sim + 1) / 2  # Normalize to 0-1

        return self._make_result(
            score=score,
            reason=f"Best match similarity: {best_sim:.3f} with reference: {best_ref[:50]}...",
            expected=references,
            actual=out_str[:100] + "..." if len(out_str) > 100 else out_str,
        )
