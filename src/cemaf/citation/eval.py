"""Citation membership as an Evaluator — plugs CitationMembershipRule into GateEvalInterceptor.

CitationMembershipRule speaks the validation.Rule protocol (errors/warnings).
GateEvalInterceptor speaks the evals.Evaluator protocol (score/passed). This
adapter bridges the two so a citation-membership check can actually gate a
DAG node, not just report a validation result nobody enforces.
"""

from typing import Any

from cemaf.citation.registry import SourceRegistry
from cemaf.citation.rules import CitationMembershipRule
from cemaf.core.types import JSON
from cemaf.evals.protocols import BaseEvaluator, EvalConfig, EvalMetric, EvalResult


class CitationMembershipEvaluator(BaseEvaluator):
    """Evaluator wrapper around CitationMembershipRule for GateEvalInterceptor.

    Scores 1.0 (passed) when every cited source_id is known to the registry,
    0.0 (failed) otherwise. Wire into GateEvalInterceptor to reject node
    output containing citations to fabricated sources.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._rule = CitationMembershipRule(registry=registry)

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CUSTOM

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        result = await self._rule.check(output)
        if result.passed:
            return self._make_result(score=1.0, reason="all cited sources known", actual=output)

        reason = "; ".join(error.message for error in result.errors)
        return self._make_result(score=0.0, reason=reason, actual=output)
