"""Tests for HaltSignal + HaltReason structured halt reporting."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.types import AgentID
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.executor import (
    DAGExecutor,
    ExecutorConfig,
    HaltReason,
    HaltSignal,
)
from cemaf.orchestration.services import RuntimeServices


class _Goal(BaseModel):
    x: int = 1


class _Result(BaseModel):
    y: int


class _CostlyAgent(Agent[_Goal, _Result]):
    @property
    def id(self) -> AgentID:
        return AgentID("Costly")

    @property
    def description(self) -> str:
        return "Reports fixed cost"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[_Result]:
        return AgentResult.ok(
            output=_Result(y=goal.x),
            state=AgentState(),
            metadata={"cost_estimate_usd": 2.0, "tokens_total": 100},
        )


def test_halt_reason_is_enum() -> None:
    assert HaltReason.BUDGET_EXHAUSTED.value == "budget_exhausted"
    assert HaltReason.QUALITY_DEGRADED.value == "quality_degraded"


def test_halt_signal_is_frozen() -> None:
    signal = HaltSignal(reason=HaltReason.BUDGET_EXHAUSTED, source="BudgetGuard")
    with pytest.raises((AttributeError, Exception)):
        signal.reason = HaltReason.QUALITY_DEGRADED  # type: ignore[misc]


def test_halt_signal_none_when_no_controllers() -> None:
    registry = AgentRegistry()
    executor: DAGExecutor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(),
    )
    assert executor._halt_signal() is None  # type: ignore[attr-defined]


def test_halt_signal_reports_budget_reason_when_budget_exhausted() -> None:
    registry = AgentRegistry()
    guard = BudgetGuard(max_cost_usd=1.0)
    guard.record_usage(cost_usd=5.0, tokens=500)  # Over cap

    executor: DAGExecutor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard),
    )
    signal = executor._halt_signal()  # type: ignore[attr-defined]
    assert signal is not None
    assert signal.reason is HaltReason.BUDGET_EXHAUSTED
    assert signal.source == "BudgetGuard"
    # detail includes state for debuggability
    assert "max_cost_usd" in signal.detail


def test_halt_signal_budget_wins_over_quality_when_both_trip() -> None:
    """Priority: budget is a harder stop — can't afford, period."""
    registry = AgentRegistry()
    guard = BudgetGuard(max_cost_usd=1.0)
    guard.record_usage(cost_usd=5.0, tokens=500)

    police = QualityPolice(config=QualityPoliceConfig(halt_threshold=0.5, window_size=1))
    # Feed a terrible score to trip the halt
    police.record_score(score=0.1, node_id="n1")

    executor: DAGExecutor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard, quality_police=police),
    )
    signal = executor._halt_signal()  # type: ignore[attr-defined]
    assert signal is not None
    # Budget (harder) takes priority
    assert signal.reason is HaltReason.BUDGET_EXHAUSTED


def test_should_halt_bool_adapter_still_works() -> None:
    """Backward compat: _should_halt() is used by node_handlers."""
    registry = AgentRegistry()
    guard = BudgetGuard(max_cost_usd=1.0)
    guard.record_usage(cost_usd=5.0, tokens=500)
    executor: DAGExecutor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=guard),
    )
    assert executor._should_halt() is True  # type: ignore[attr-defined]
