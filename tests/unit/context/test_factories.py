"""Tests for context factory helpers."""

import pytest

from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    GreedySelectionAlgorithm,
    KnapsackSelectionAlgorithm,
    OptimalSelectionAlgorithm,
    SelectionResult,
)
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.factories import (
    CompilerConfig,
    context_selection_algorithm_registry,
    create_context_compiler_from_config,
    create_context_selection_algorithm,
    create_token_budget,
    create_token_estimator,
    create_token_estimator_from_config,
    token_estimator_registry,
)
from cemaf.context.source import ContextSource


class CustomTokenEstimator:
    def __init__(self, tokens: int) -> None:
        self._tokens = tokens

    def estimate(self, text: str) -> int:
        return self._tokens


class CustomSelectionAlgorithm:
    def select_sources(self, sources: list[ContextSource], budget) -> SelectionResult:  # noqa: ANN001
        return SelectionResult(
            selected_sources=tuple(sources),
            total_tokens=sum(source.token_count or 0 for source in sources),
            metadata={"selection_method": "custom"},
        )


def test_create_token_budget_uses_explicit_max_tokens() -> None:
    budget = create_token_budget(max_tokens=1234)

    assert budget.max_tokens == 1234


def test_create_token_budget_can_derive_from_model() -> None:
    budget = create_token_budget(model="gpt-4o")

    assert budget.max_tokens == 128_000


def test_create_token_estimator_returns_simple_estimator_by_default() -> None:
    estimator = create_token_estimator()

    assert isinstance(estimator, SimpleTokenEstimator)


def test_create_token_estimator_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomTokenEstimator(tokens=13)

    token_estimator_registry.register(backend="custom-token-estimator", factory=_factory)

    estimator = create_token_estimator(
        estimator_type="custom-token-estimator",
        model="custom-model",
        chars_per_token=2.5,
        calibration="strict",
    )

    assert estimator.estimate("anything") == 13
    assert created["args"]["model"] == "custom-model"
    assert created["args"]["chars_per_token"] == 2.5
    assert created["args"]["calibration"] == "strict"


def test_create_token_estimator_from_config_supports_custom_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _factory(**kwargs):
        return CustomTokenEstimator(tokens=int(kwargs["tokens"]))

    token_estimator_registry.register(backend="env-token-estimator", factory=_factory)
    monkeypatch.setenv("CEMAF_CONTEXT_TOKEN_ESTIMATOR_BACKEND", "env-token-estimator")
    monkeypatch.setenv("CEMAF_CONTEXT_TOKEN_ESTIMATOR_MODEL", "env-model")
    monkeypatch.setenv("CEMAF_CONTEXT_CHARS_PER_TOKEN", "3.25")

    estimator = create_token_estimator_from_config(tokens=21)

    assert estimator.estimate("anything") == 21


def test_create_context_selection_algorithm_returns_builtin_algorithms() -> None:
    assert isinstance(create_context_selection_algorithm("greedy"), GreedySelectionAlgorithm)
    assert isinstance(create_context_selection_algorithm("knapsack"), KnapsackSelectionAlgorithm)
    assert isinstance(
        create_context_selection_algorithm("optimal", max_sources=5),
        OptimalSelectionAlgorithm,
    )


def test_create_context_selection_algorithm_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomSelectionAlgorithm()

    context_selection_algorithm_registry.register(backend="custom-selection", factory=_factory)

    algorithm = create_context_selection_algorithm("custom-selection", mode="strict")

    assert isinstance(algorithm, ContextSelectionAlgorithm)
    assert created["args"]["mode"] == "strict"


def test_create_priority_compiler_config_uses_configured_algorithm() -> None:
    from cemaf.context.factories import create_priority_compiler

    compiler = create_priority_compiler(
        token_estimator=CustomTokenEstimator(tokens=1),
        config=CompilerConfig(algorithm="knapsack"),
    )

    assert isinstance(compiler._algorithm, KnapsackSelectionAlgorithm)  # noqa: SLF001


def test_create_priority_compiler_config_supports_custom_algorithm() -> None:
    from cemaf.context.factories import create_priority_compiler

    context_selection_algorithm_registry.register(
        backend="compiler-custom-selection",
        factory=lambda **_: CustomSelectionAlgorithm(),
    )

    compiler = create_priority_compiler(
        token_estimator=CustomTokenEstimator(tokens=1),
        config=CompilerConfig(algorithm="compiler-custom-selection"),
    )

    assert isinstance(compiler._algorithm, CustomSelectionAlgorithm)  # noqa: SLF001


def test_context_compiler_from_config_uses_env_token_estimator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_estimator_registry.register(
        backend="compiler-env-token-estimator",
        factory=lambda **_: CustomTokenEstimator(tokens=8),
    )
    monkeypatch.setenv("CEMAF_CONTEXT_TOKEN_ESTIMATOR_BACKEND", "compiler-env-token-estimator")

    compiler = create_context_compiler_from_config()

    assert isinstance(compiler, PriorityContextCompiler)
    assert compiler._estimator.estimate("anything") == 8  # noqa: SLF001
