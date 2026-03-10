"""Tests for semantic similarity evaluators and cosine similarity."""

import math

import pytest

from cemaf.evals.protocols import EvalMetric
from cemaf.evals.semantic import (
    MultiReferenceSemanticEvaluator,
    SemanticSimilarityEvaluator,
    cosine_similarity,
)


class FakeEmbeddingProvider:
    """Deterministic embedding provider for testing."""

    def __init__(self, *, mapping: dict[str, tuple[float, ...]] | None = None) -> None:
        self._mapping = mapping or {}

    @property
    def dimension(self) -> int:
        return 3

    @property
    def model_name(self) -> str:
        return "fake-embeddings"

    async def embed(self, text: str) -> tuple[float, ...]:
        if text in self._mapping:
            return self._mapping[text]
        # Default: hash-based deterministic embedding
        h = hash(text) % 1000
        return (
            math.sin(h),
            math.cos(h),
            math.sin(h * 2),
        )

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [await self.embed(text=t) for t in texts]


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = (1.0, 2.0, 3.0)
        result = cosine_similarity(a=v, b=v)
        assert result == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = (1.0, 0.0, 0.0)
        b = (0.0, 1.0, 0.0)
        result = cosine_similarity(a=a, b=b)
        assert result == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = (1.0, 0.0, 0.0)
        b = (-1.0, 0.0, 0.0)
        result = cosine_similarity(a=a, b=b)
        assert result == pytest.approx(-1.0)

    def test_dimension_mismatch_raises(self):
        with pytest.raises(ValueError, match="Dimension mismatch"):
            cosine_similarity(a=(1.0, 2.0), b=(1.0, 2.0, 3.0))

    def test_zero_norm_first_vector(self):
        result = cosine_similarity(a=(0.0, 0.0, 0.0), b=(1.0, 2.0, 3.0))
        assert result == 0.0

    def test_zero_norm_second_vector(self):
        result = cosine_similarity(a=(1.0, 2.0, 3.0), b=(0.0, 0.0, 0.0))
        assert result == 0.0

    def test_zero_norm_both_vectors(self):
        result = cosine_similarity(a=(0.0, 0.0), b=(0.0, 0.0))
        assert result == 0.0

    def test_similar_vectors_high_score(self):
        a = (1.0, 2.0, 3.0)
        b = (1.1, 2.1, 3.1)
        result = cosine_similarity(a=a, b=b)
        assert result > 0.99

    def test_single_dimension(self):
        result = cosine_similarity(a=(5.0,), b=(3.0,))
        assert result == pytest.approx(1.0)


class TestSemanticSimilarityEvaluator:
    @pytest.mark.asyncio
    async def test_similar_texts_high_score(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "the sky is blue": (0.9, 0.1, 0.0),
                "blue is the color of the sky": (0.85, 0.15, 0.05),
            }
        )
        evaluator = SemanticSimilarityEvaluator(
            embedding_provider=provider,
            similarity_threshold=0.8,
        )

        result = await evaluator.evaluate(
            output="the sky is blue",
            expected="blue is the color of the sky",
        )

        assert result.score > 0.9
        assert result.passed is True
        assert result.metric == EvalMetric.SEMANTIC_SIMILARITY

    @pytest.mark.asyncio
    async def test_different_texts_low_score(self):
        from cemaf.evals.protocols import EvalConfig

        provider = FakeEmbeddingProvider(
            mapping={
                "apples are red": (1.0, 0.0, 0.0),
                "quantum computing theory": (-1.0, 0.0, 0.0),
            }
        )
        evaluator = SemanticSimilarityEvaluator(
            embedding_provider=provider,
            similarity_threshold=0.8,
            config=EvalConfig(pass_threshold=0.5),
        )

        result = await evaluator.evaluate(
            output="apples are red",
            expected="quantum computing theory",
        )

        # Opposite vectors => cosine=-1 => normalized=(-1+1)/2=0.0
        assert result.score == pytest.approx(0.0)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_no_expected_value_returns_zero(self):
        provider = FakeEmbeddingProvider()
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="hello", expected=None)

        assert result.score == 0.0
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_both_empty_returns_one(self):
        provider = FakeEmbeddingProvider()
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="  ", expected="  ")

        assert result.score == pytest.approx(1.0)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_one_empty_returns_zero(self):
        provider = FakeEmbeddingProvider()
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="hello", expected="  ")

        assert result.score == 0.0
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_output_empty_expected_nonempty(self):
        provider = FakeEmbeddingProvider()
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="  ", expected="hello")

        assert result.score == 0.0
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "cat": (0.9, 0.1, 0.0),
                "kitten": (0.7, 0.3, 0.1),
            }
        )
        evaluator = SemanticSimilarityEvaluator(
            embedding_provider=provider,
            similarity_threshold=0.95,
        )

        result = await evaluator.evaluate(output="cat", expected="kitten")

        # Score depends on cosine similarity, threshold only appears in reason
        assert result.metric == EvalMetric.SEMANTIC_SIMILARITY
        assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_score_normalization_negative_cosine(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "positive": (1.0, 0.0, 0.0),
                "negative": (-1.0, 0.0, 0.0),
            }
        )
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="positive", expected="negative")

        # cosine = -1.0, normalized = (-1+1)/2 = 0.0
        assert result.score == pytest.approx(0.0)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_identical_texts_perfect_score(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "exact same": (0.5, 0.5, 0.5),
            }
        )
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="exact same", expected="exact same")

        # Same embedding => cosine=1.0 => normalized=1.0
        assert result.score == pytest.approx(1.0)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_result_contains_reason_with_similarity(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "a": (1.0, 0.0, 0.0),
                "b": (0.0, 1.0, 0.0),
            }
        )
        evaluator = SemanticSimilarityEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="a", expected="b")

        assert "Cosine similarity" in result.reason
        assert "threshold" in result.reason


class TestMultiReferenceSemanticEvaluator:
    @pytest.mark.asyncio
    async def test_single_reference_string(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "hello": (1.0, 0.0, 0.0),
                "hi": (0.95, 0.05, 0.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
        )

        result = await evaluator.evaluate(output="hello", expected="hi")

        assert result.score > 0.9
        assert result.metric == EvalMetric.SEMANTIC_SIMILARITY

    @pytest.mark.asyncio
    async def test_multiple_references_picks_best(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "dog": (1.0, 0.0, 0.0),
                "canine": (0.95, 0.05, 0.0),
                "feline": (0.0, 1.0, 0.0),
                "automobile": (0.0, 0.0, 1.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
        )

        result = await evaluator.evaluate(
            output="dog",
            expected=["canine", "feline", "automobile"],
        )

        # "canine" is closest to "dog"
        assert result.score > 0.9
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_no_expected_returns_zero(self):
        provider = FakeEmbeddingProvider()
        evaluator = MultiReferenceSemanticEvaluator(embedding_provider=provider)

        result = await evaluator.evaluate(output="hello", expected=None)

        assert result.score == 0.0
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_list_input_expected(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "cat": (1.0, 0.0, 0.0),
                "kitty": (0.9, 0.1, 0.0),
                "dog": (0.0, 1.0, 0.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
        )

        result = await evaluator.evaluate(
            output="cat",
            expected=["kitty", "dog"],
        )

        # "kitty" should be the best match
        assert result.score > 0.8
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_tuple_input_expected(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "yes": (1.0, 0.0, 0.0),
                "affirmative": (0.9, 0.1, 0.0),
                "no": (-1.0, 0.0, 0.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
        )

        result = await evaluator.evaluate(
            output="yes",
            expected=("affirmative", "no"),
        )

        # "affirmative" is best match
        assert result.score > 0.8

    @pytest.mark.asyncio
    async def test_non_string_expected_converted(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "hello": (1.0, 0.0, 0.0),
                "42": (0.0, 1.0, 0.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
        )

        result = await evaluator.evaluate(output="hello", expected=42)

        # expected=42 => str(42) => "42"
        assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_result_reason_contains_best_match(self):
        provider = FakeEmbeddingProvider(
            mapping={
                "output": (1.0, 0.0, 0.0),
                "ref1": (0.9, 0.1, 0.0),
                "ref2": (0.0, 1.0, 0.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
        )

        result = await evaluator.evaluate(
            output="output",
            expected=["ref1", "ref2"],
        )

        assert "Best match" in result.reason
        assert "similarity" in result.reason

    @pytest.mark.asyncio
    async def test_all_references_dissimilar_low_score(self):
        from cemaf.evals.protocols import EvalConfig

        provider = FakeEmbeddingProvider(
            mapping={
                "query": (1.0, 0.0, 0.0),
                "ref_a": (-1.0, 0.0, 0.0),
                "ref_b": (-0.9, -0.1, 0.0),
            }
        )
        evaluator = MultiReferenceSemanticEvaluator(
            embedding_provider=provider,
            config=EvalConfig(pass_threshold=0.5),
        )

        result = await evaluator.evaluate(
            output="query",
            expected=["ref_a", "ref_b"],
        )

        # Both near-opposite => best cosine near -1 => normalized near 0
        assert result.score < 0.1
        assert result.passed is False
