"""
CEMAF DataSources + PullInterceptor — enterprise connectors, budget-safe (SPEC-02).

A `DataSource` is a read-only enterprise connector (CRM, ticketing system,
internal DB) — the `DataSourceRegistry` structurally rejects any implementation
exposing public surface beyond `retrieve`/`health`/`source_id`/`capabilities`.
`PullInterceptor` runs before `agent.run()`: it pulls context from every
registered `DataSource` (and the knowledge graph, if wired), merges by
priority/confidence/recency, and writes the result into
`AgentContext.artifacts["surfaced_sources"]` for the agent to read.

This example also demonstrates the token-budget reconciliation: when a real
`TokenBudget` is passed to `PullInterceptor`, it caps its own contribution
against whatever `ContextNodeExecutor`'s compiled context already spent — so
`surfaced_sources` plus `compiled_context` can never together exceed the
model's real context window.

Usage:
    uv run python examples/pull_interceptor_datasources.py
"""

import asyncio
from typing import ClassVar

from pydantic import BaseModel

from cemaf import (
    DAG,
    Agent,
    AgentContext,
    AgentRegistry,
    AgentResult,
    AgentState,
    Node,
    RuntimeServices,
    TokenBudget,
    create_executor,
)
from cemaf.citation.models import Citation
from cemaf.core.types import AgentID
from cemaf.datasources.models import (
    CiteableChunk,
    DataSourceCapability,
    HealthStatus,
    RetrievalQuery,
    SourceKind,
)
from cemaf.datasources.registry import DataSourceRegistry
from cemaf.interceptors import create_interceptor_pipeline
from cemaf.orchestration.factories import create_pull_interceptor


class OrderCRM:
    """A read-only enterprise connector — registry rejects any extra public method."""

    source_id: ClassVar[str] = "order_crm"
    capabilities: ClassVar[frozenset[DataSourceCapability]] = frozenset({DataSourceCapability.SEARCH})

    async def retrieve(self, *, query: RetrievalQuery, budget: TokenBudget) -> tuple[CiteableChunk, ...]:
        citation = Citation(
            id="order-42",
            source_id=self.source_id,
            source_type="crm_record",
            url="https://crm.example/order/42",
        )
        chunk = CiteableChunk(
            chunk_id="order-42",
            content="Order #42: shipped 2026-07-10, customer VIP tier.",
            citation=citation,
            token_count=20,
            source_kind=SourceKind.DATASOURCE,
        )
        return (chunk,) if chunk.token_count <= budget.max_tokens else ()

    async def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY


class SupportGoal(BaseModel):
    pass


class SupportResult(BaseModel):
    surfaced_source_ids: list[str]


class SupportAgent(Agent[SupportGoal, SupportResult]):
    """Reads whatever PullInterceptor surfaced — no direct CRM dependency."""

    @property
    def id(self) -> AgentID:
        return AgentID("support_agent")

    @property
    def description(self) -> str:
        return "answers order status questions"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: SupportGoal, context: AgentContext) -> AgentResult[SupportResult]:
        surfaced = context.artifacts.get("surfaced_sources", ())
        source_ids = [chunk.citation.source_id for chunk in surfaced]
        return AgentResult.ok(output=SupportResult(surfaced_source_ids=source_ids), state=AgentState())


def _dag() -> DAG:
    node = Node.agent(
        id="support_lookup",
        name="check order 42 status",
        agent_id="support_agent",
        output_key="result",
    )
    return DAG(name="support_dag", description="order lookup via DataSource").add_node(node=node)


def _registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=SupportAgent(), goal_type=SupportGoal)
    return registry


async def main() -> None:
    data_sources = DataSourceRegistry()
    data_sources.register(OrderCRM())

    # Real model-window budget: compiled context has already spent 900 of the
    # 1000 available tokens, so PullInterceptor must shrink pull_tokens=500
    # down to the 100 tokens actually left, not just cap against pull_tokens.
    token_budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
    services = RuntimeServices(data_source_registry=data_sources, token_budget=token_budget)
    pull_interceptor = create_pull_interceptor(services=services, pull_tokens=500)
    pipeline = create_interceptor_pipeline(interceptors=(pull_interceptor,))

    executor = create_executor(
        agent_registry=_registry(),
        services=RuntimeServices(
            data_source_registry=data_sources, token_budget=token_budget, interceptor_pipeline=pipeline
        ),
    )

    run = await executor.run(dag=_dag())
    print(f"Status: {run.status.value}")
    node_result = next(r for r in run.node_results if r.node_id == "support_lookup")
    print(f"Surfaced source ids: {node_result.output}")
    print("→ OrderCRM's chunk (20 tokens) reached the agent without the agent knowing OrderCRM exists.")

    # Now show the reconciliation actually biting: compiled context already
    # spent almost the whole budget, so PullInterceptor's own contribution
    # collapses to (near) zero even though pull_tokens=500 would otherwise allow it.
    tight_pull_interceptor = create_pull_interceptor(services=services, pull_tokens=500)
    almost_full_context = AgentContext(
        run_id="demo", agent_id="support_agent", artifacts={"compiled_context_tokens": 990}
    )
    decision = await tight_pull_interceptor.pre(node=_dag().nodes[0], context=almost_full_context)
    surfaced = decision.enriched_context.artifacts["surfaced_sources"] if decision.enriched_context else ()
    print(
        f"\nWith compiled_context_tokens=990 of {token_budget.max_tokens}: "
        f"surfaced {len(surfaced)} chunks (only ~10 tokens of headroom left)."
    )


if __name__ == "__main__":
    asyncio.run(main())
