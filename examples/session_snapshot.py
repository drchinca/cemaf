"""
CEMAF Operator Plane — cemaf.session.v1 read-only run snapshot (SPEC-14).

Run a real DAG, then project the executor's ExecutionResult into a versioned, JSON-serializable
SessionSnapshot — the stable public contract a CLI / service / MCP / dashboard renders from,
instead of coupling to internal dataclasses. Deterministic and read-only; absent optional
services are reported as "absent".

Usage:
    uv run python examples/session_snapshot.py
"""

import asyncio

from pydantic import BaseModel

from cemaf import DAG, Agent, AgentContext, AgentRegistry, AgentResult, AgentState, Node, create_executor
from cemaf.core.types import AgentID
from cemaf.operator import snapshot_from_execution_result


class GreetGoal(BaseModel):
    name: str = "World"


class GreetResult(BaseModel):
    message: str


class GreeterAgent(Agent[GreetGoal, GreetResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Greeter")

    @property
    def description(self) -> str:
        return "Greets by name"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: GreetGoal, context: AgentContext) -> AgentResult[GreetResult]:
        return AgentResult.ok(output=GreetResult(message=f"Hello, {goal.name}!"), state=AgentState())


async def main() -> None:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=GreeterAgent(), goal_type=GreetGoal)

    dag = DAG(name="greet-pipeline", description="one-node demo")
    dag = dag.add_node(
        node=Node.agent(id="greet", name="Greeter", agent_id="Greeter", output_key="greeting")
    )

    result = await create_executor(agent_registry=registry).run(dag=dag)

    # Project the real ExecutionResult into the cemaf.session.v1 contract.
    snapshot = snapshot_from_execution_result(result, services_present=("run_logger",))

    print(f"schema_version : {snapshot.schema_version}")
    print(f"run            : {snapshot.run.id}  state={snapshot.run.state.value}")
    print(f"workers        : {[(w.id, w.state.value, w.health.value) for w in snapshot.workers]}")
    print(f"services       : {dict(snapshot.runtime.services)}")
    print("\nFull JSON snapshot (what a dashboard/MCP would consume):")
    print(snapshot.to_json())


if __name__ == "__main__":
    asyncio.run(main())
