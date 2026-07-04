"""Unit tests for PolicyInterceptor and its default engine."""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext
from cemaf.interceptors.policy import (
    AllowAllEngine,
    PolicyDecision,
    PolicyEffect,
    PolicyEngine,
    PolicyInterceptor,
)
from cemaf.interceptors.protocols import PreInterceptor
from cemaf.interceptors.types import DecisionKind
from cemaf.orchestration.dag import Node


def _ctx() -> AgentContext:
    return AgentContext(run_id="run_1", agent_id="agent_a")


def _node() -> Node:
    return Node.agent(id="n1", name="n1", agent_id="agent_a", output_key="out")


class TestPolicyDecision:
    def test_allow_can_omit_reason(self) -> None:
        d = PolicyDecision(effect=PolicyEffect.ALLOW)
        assert d.effect is PolicyEffect.ALLOW

    def test_deny_without_reason_raises(self) -> None:
        with pytest.raises(ValueError):
            PolicyDecision(effect=PolicyEffect.DENY)


class TestAllowAllEngine:
    @pytest.mark.asyncio
    async def test_returns_allow(self) -> None:
        engine = AllowAllEngine()
        d = await engine.decide(node=_node(), context=_ctx())
        assert d.effect is PolicyEffect.ALLOW


class TestPolicyInterceptor:
    def test_is_pre_interceptor(self) -> None:
        assert isinstance(PolicyInterceptor(engine=AllowAllEngine()), PreInterceptor)

    @pytest.mark.asyncio
    async def test_allow_accepts(self) -> None:
        icept = PolicyInterceptor(engine=AllowAllEngine())
        d = await icept.pre(node=_node(), context=_ctx())
        assert d.kind is DecisionKind.ACCEPT

    @pytest.mark.asyncio
    async def test_deny_rejects_with_reason(self) -> None:
        class _Deny:
            async def decide(self, *, node, context):
                return PolicyDecision(
                    effect=PolicyEffect.DENY,
                    reason="agent_a not in workspace ws_1",
                    rule_id="rule_ws_scoped",
                )

        icept = PolicyInterceptor(engine=_Deny())
        d = await icept.pre(node=_node(), context=_ctx())
        assert d.kind is DecisionKind.REJECT
        assert "policy denied" in (d.reason or "")
        assert "rule_ws_scoped" in (d.reason or "")

    @pytest.mark.asyncio
    async def test_unknown_treated_as_allow(self) -> None:
        """Engine having no opinion is not a rejection — the seam is transparent."""

        class _NoOpinion:
            async def decide(self, *, node, context):
                return PolicyDecision(effect=PolicyEffect.UNKNOWN)

        icept = PolicyInterceptor(engine=_NoOpinion())
        d = await icept.pre(node=_node(), context=_ctx())
        assert d.kind is DecisionKind.ACCEPT

    def test_engine_is_structural(self) -> None:
        """A duck-typed engine satisfies the runtime-checkable PolicyEngine protocol."""

        class _Duck:
            async def decide(self, *, node, context):
                return PolicyDecision(effect=PolicyEffect.ALLOW)

        assert isinstance(_Duck(), PolicyEngine)
