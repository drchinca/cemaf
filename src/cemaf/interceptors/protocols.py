"""Interceptor protocols — two SINGLE-method protocols, not one two-method protocol.

`@runtime_checkable` isinstance only verifies attribute *presence*; a POST-only
interceptor has no `pre`, so it must not be required to satisfy a combined
protocol. The pipeline detects which phases an interceptor implements via
`isinstance` against each split protocol. An interceptor MAY implement both.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cemaf.agents.base import AgentContext
from cemaf.interceptors.types import PostflightDecision, PreflightDecision
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult


@runtime_checkable
class PreInterceptor(Protocol):
    """Runs before agent.run(); may enrich the context or REJECT (skip the agent)."""

    @property
    def interceptor_id(self) -> str: ...

    async def pre(self, *, node: Node, context: AgentContext) -> PreflightDecision: ...


@runtime_checkable
class PostInterceptor(Protocol):
    """Runs after a successful agent.run(); may REJECT (fail the node)."""

    @property
    def interceptor_id(self) -> str: ...

    async def post(self, *, node: Node, context: AgentContext, result: NodeResult) -> PostflightDecision: ...


# An interceptor is anything implementing at least one phase.
Interceptor = PreInterceptor | PostInterceptor
