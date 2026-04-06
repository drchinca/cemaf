"""
CEMAF Hello World — Define an agent, build a DAG, run it.

Usage:
    uv run python examples/hello_world.py
"""

import asyncio

from pydantic import BaseModel, Field

from cemaf import (
    Agent,
    AgentContext,
    AgentResult,
    AgentRegistry,
    DAG,
    Edge,
    Node,
    create_executor,
)
from cemaf.agents.base import AgentState
from cemaf.core.types import AgentID


# 1. Define goal and result models
class GreetGoal(BaseModel):
    name: str = Field(description="Name to greet")


class GreetResult(BaseModel):
    message: str = Field(description="Greeting message")


# 2. Implement an agent
class GreeterAgent(Agent[GreetGoal, GreetResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Greeter")

    @property
    def description(self) -> str:
        return "Greets people by name"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: GreetGoal,
        context: AgentContext,
    ) -> AgentResult[GreetResult]:
        result = GreetResult(message=f"Hello, {goal.name}! Welcome to CEMAF.")
        return AgentResult.ok(output=result, state=AgentState())


# 3. Register and build DAG
async def main() -> None:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=GreeterAgent(), goal_type=GreetGoal)

    dag = DAG(name="hello", description="Hello world pipeline")
    dag = dag.add_node(
        node=Node.agent(
            id="greet",
            name="Greeter",
            agent_id="Greeter",
            output_key="greeting",
        )
    )

    executor = create_executor(agent_registry=registry)
    final_context = await executor.run(dag=dag)

    print(f"DAG completed. Context keys: {list(final_context.data.keys())}")
    if "greeting" in final_context.data:
        print(f"Result: {final_context.data['greeting']}")


if __name__ == "__main__":
    asyncio.run(main())
