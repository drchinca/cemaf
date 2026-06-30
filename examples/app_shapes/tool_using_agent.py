"""App shape: an agent calls a flaky tool that self-heals via retry — in a DAG.

Use-case: an agent depends on a flaky external API. The transient failure should
recover on its own, and the whole thing should run inside the orchestrator — not
a hand-rolled retry loop bolted onto a script.

Best practice shown: retry is `cemaf.resilience` (declarative `@with_retry`),
the call is a `@tool`, and execution goes through `create_executor` — three
primitives composed, zero bespoke control flow.

Usage:
    uv run python examples/app_shapes/tool_using_agent.py
"""

import asyncio
import json

from pydantic import BaseModel

from cemaf import (
    DAG,
    Agent,
    AgentContext,
    AgentRegistry,
    AgentResult,
    AgentState,
    Node,
    create_executor,
    tool,
)
from cemaf.core.result import Result
from cemaf.core.types import AgentID
from cemaf.resilience import with_retry

# Simulates an external endpoint that fails once, then succeeds.
_attempts = {"count": 0}


@with_retry(max_attempts=3, initial_delay=0.0, retry_on_exceptions=(ConnectionError,))
async def _call_quote_api(symbol: str) -> dict[str, object]:
    _attempts["count"] += 1
    if _attempts["count"] < 2:
        raise ConnectionError("upstream quote service unavailable")
    return {"symbol": symbol, "price": 42.0, "attempts": _attempts["count"]}


@tool(
    name="fetch_quote",
    description="Fetch a price quote for a ticker symbol",
    parameters={"type": "object", "properties": {"symbol": {"type": "string"}}},
    required=("symbol",),
)
async def fetch_quote(symbol: str) -> Result[dict[str, object]]:
    return Result.ok(await _call_quote_api(symbol))


class QuoteGoal(BaseModel):
    symbol: str


class QuoteResult(BaseModel):
    symbol: str
    price: float
    attempts: int


class QuoteAgent(Agent[QuoteGoal, QuoteResult]):
    """Agent that fetches a quote through the resilient tool."""

    @property
    def id(self) -> AgentID:
        return AgentID("QuoteAgent")

    @property
    def description(self) -> str:
        return "Fetches a price quote via the fetch_quote tool with retry"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: QuoteGoal, context: AgentContext) -> AgentResult[QuoteResult]:
        result = await fetch_quote.execute(symbol=goal.symbol)
        if not result.success:
            return AgentResult.fail(error=result.error or "quote failed", state=AgentState())
        return AgentResult.ok(output=QuoteResult(**result.data), state=AgentState())


async def main() -> None:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=QuoteAgent(), goal_type=QuoteGoal)

    dag = DAG(name="quote-pipeline")
    dag = dag.add_node(
        node=Node.agent(
            id="quote",
            name="Fetch Quote",
            agent_id="QuoteAgent",
            input_mapping={"symbol": "ACME"},
            output_key="quote",
        )
    )

    executor = create_executor(agent_registry=registry)
    run = await executor.run(dag=dag)

    # The executor stores structured agent output as JSON in the context.
    quote = QuoteResult(**json.loads(run.final_context.data["quote"]))
    # Proof: the transient failure recovered (2 attempts) AND it ran in the DAG.
    assert run.status.value == "completed"
    assert quote.attempts == 2

    print(f"dag status : {run.status.value}")
    print(f"attempts   : {quote.attempts} (failed once, then recovered)")
    print(f"quote      : {quote.symbol} @ ${quote.price}")


if __name__ == "__main__":
    asyncio.run(main())
