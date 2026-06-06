"""GateEvalInterceptor — the first real station: a POST gate that actually blocks.

Closes the standing audit P0 (GATE evaluators only emitted an event; nothing
blocked). As a POST interceptor it runs evaluators on the node output and REJECTs
when any fails — flipping the NodeResult to failure so the existing
`ON_SUCCESS`/`JSON_RULE` edge logic blocks downstream nodes. No new gating path.
"""

from __future__ import annotations

from cemaf.agents.base import AgentContext
from cemaf.evals.protocols import Evaluator
from cemaf.interceptors.types import DecisionKind, PostflightDecision
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult


class GateEvalInterceptor:
    """POST gate: REJECT when any bound evaluator fails on the node output.

    `node_pattern` is the node id this gate applies to, or "*" for all AGENT nodes.
    A node that does not match is passed through (ACCEPT). An evaluator result with
    `passed=False` or `score < threshold` → REJECT.
    """

    def __init__(
        self,
        *,
        evaluators: tuple[Evaluator, ...],
        node_pattern: str = "*",
        threshold: float = 0.5,
        interceptor_id: str | None = None,
    ) -> None:
        if not evaluators:
            raise ValueError("GateEvalInterceptor requires at least one evaluator")
        self._evaluators = evaluators
        self._pattern = node_pattern
        self._threshold = threshold
        # id parameterised by pattern so multiple gates coexist without collision
        self._id = interceptor_id or f"gate_eval:{node_pattern}"

    @property
    def interceptor_id(self) -> str:
        return self._id

    def _matches(self, node: Node) -> bool:
        return self._pattern == "*" or self._pattern == str(node.id)

    async def post(self, *, node: Node, context: AgentContext, result: NodeResult) -> PostflightDecision:
        if not self._matches(node):
            return PostflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id)

        output = result.output
        for evaluator in self._evaluators:
            eval_result = await evaluator.evaluate(output=output)
            if not eval_result.passed or eval_result.score < self._threshold:
                metric = getattr(eval_result.metric, "value", eval_result.metric)
                detail = eval_result.reason or "no detail"
                return PostflightDecision(
                    kind=DecisionKind.REJECT,
                    interceptor_id=self._id,
                    reason=(
                        f"gate failed: {metric} score={eval_result.score:.2f} "
                        f"< {self._threshold:.2f} ({detail})"
                    ),
                )
        return PostflightDecision(
            kind=DecisionKind.ACCEPT,
            interceptor_id=self._id,
            metadata={"gate": "passed", "evaluators": len(self._evaluators)},
        )
