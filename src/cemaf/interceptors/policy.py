"""PolicyInterceptor — a PRE station that asks a pluggable engine to authorise the node.

The interceptor is vendor-neutral by design: it depends only on the small
`PolicyEngine` protocol, not on any policy language, bundle format, or SDK.
Real engines (in-house rule tables, OPA/Rego adapters, external policy
services, backend-native authz) are BYO — they land as adapters, not as
dependencies of this module.

Framing:

- The interceptor is the **seam**. It runs on the same interceptor spine
  that GateEvalInterceptor uses.
- The engine is the **decision**. A default `AllowAllEngine` ships so
  wiring the seam is safe in dev/CI; production wiring supplies a real
  engine.
- Data classification (`ContextPatch.security_level`) is available to
  the engine as a resource attribute — the interceptor does not compile
  policy against it, it just passes the node/context through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from cemaf.agents.base import AgentContext
from cemaf.core.types import JSON
from cemaf.interceptors.types import DecisionKind, PreflightDecision
from cemaf.orchestration.dag import Node


class PolicyEffect(StrEnum):
    """Outcome of an authorisation decision."""

    ALLOW = "allow"
    DENY = "deny"
    UNKNOWN = "unknown"  # engine has no opinion; interceptor treats as ALLOW


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """One engine decision. `reason` is required when the effect is DENY.

    The interceptor stamps this decision onto the interceptor metadata for
    provenance so audit trails can attribute a rejection to its rule.
    """

    effect: PolicyEffect
    reason: str | None = None
    rule_id: str | None = None
    metadata: JSON = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effect is PolicyEffect.DENY and not (self.reason and self.reason.strip()):
            raise ValueError("PolicyDecision DENY requires a non-empty reason")


@runtime_checkable
class PolicyEngine(Protocol):
    """Structural contract for authorisation engines.

    One coroutine: given the node about to run and its agent context,
    return an ALLOW / DENY / UNKNOWN decision. Engines are free to
    inspect anything reachable from those two arguments — actor identity
    (``context.agent_id``), workspace scoping (``context.global_memory``),
    data classification on prior patches, or their own out-of-band state.
    """

    async def decide(self, *, node: Node, context: AgentContext) -> PolicyDecision: ...


class AllowAllEngine:
    """Development default — every node is authorised.

    Ship an adapter for a real engine (in-house table, OPA/Rego, backend-
    native authz) before running against real workloads. This class exists
    only so the interceptor seam can be wired in tests and dev without
    forcing an engine choice.
    """

    async def decide(self, *, node: Node, context: AgentContext) -> PolicyDecision:
        return PolicyDecision(effect=PolicyEffect.ALLOW, rule_id="allow_all")


class PolicyInterceptor:
    """PRE gate that REJECTs a node when the bound engine denies it.

    ALLOW / UNKNOWN → ACCEPT (interceptor is transparent).
    DENY → REJECT with the engine's reason; downstream nodes never run
    (the DAG's ON_SUCCESS edges see the failure and skip).
    """

    def __init__(
        self,
        *,
        engine: PolicyEngine,
        interceptor_id: str = "policy",
    ) -> None:
        self._engine = engine
        self._id = interceptor_id

    @property
    def interceptor_id(self) -> str:
        return self._id

    async def pre(self, *, node: Node, context: AgentContext) -> PreflightDecision:
        decision = await self._engine.decide(node=node, context=context)
        if decision.effect is PolicyEffect.DENY:
            rule = f" ({decision.rule_id})" if decision.rule_id else ""
            return PreflightDecision(
                kind=DecisionKind.REJECT,
                interceptor_id=self._id,
                reason=f"policy denied{rule}: {decision.reason}",
            )
        return PreflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id)
