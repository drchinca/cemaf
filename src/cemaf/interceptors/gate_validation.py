"""POST interceptor that turns framework validation pipelines into real gates."""

from __future__ import annotations

from cemaf.agents.base import AgentContext
from cemaf.interceptors.gate_eval import GateFailureMode
from cemaf.interceptors.types import DecisionKind, PostflightDecision, RecoveryHint
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult
from cemaf.validation.protocols import ValidationError, ValidationWarning, Validator


class GateValidationInterceptor:
    """Run a ``Validator`` on structured output and reject or recover on issues."""

    def __init__(
        self,
        *,
        validator: Validator,
        node_pattern: str = "*",
        fail_on_warnings: bool = False,
        on_failure: GateFailureMode = GateFailureMode.REJECT,
        interceptor_id: str | None = None,
    ) -> None:
        self._validator = validator
        self._pattern = node_pattern
        self._fail_on_warnings = fail_on_warnings
        self._on_failure = on_failure
        self._id = interceptor_id or f"gate_validation:{node_pattern}"

    @property
    def interceptor_id(self) -> str:
        return self._id

    async def post(
        self,
        *,
        node: Node,
        context: AgentContext,
        result: NodeResult,
    ) -> PostflightDecision:
        if self._pattern != "*" and self._pattern != str(node.id):
            return PostflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id)

        metadata = result.metadata or {}
        structured_output = metadata.get("_context_output")
        data = structured_output if structured_output is not None else result.output
        validation = await self._validator.validate(
            data,
            context={
                "run_id": context.run_id,
                "agent_id": context.agent_id,
                "node_id": str(node.id),
            },
        )
        blocking: list[ValidationError | ValidationWarning] = [*validation.errors]
        if self._fail_on_warnings:
            blocking.extend(validation.warnings)

        if validation.passed and not blocking:
            return PostflightDecision(
                kind=DecisionKind.ACCEPT,
                interceptor_id=self._id,
                metadata={
                    "gate": "passed",
                    "warnings": len(validation.warnings),
                    "validator": type(self._validator).__name__,
                },
            )

        first = blocking[0] if blocking else None
        code = first.code if first is not None else "VALIDATION_FAILED"
        detail = first.message if first is not None else "validator returned passed=False"
        suggestions = [
            suggestion
            for suggestion in (
                getattr(first, "suggestion", None) if first is not None else None,
                *validation.suggestions,
            )
            if suggestion
        ]
        reason = f"validation failed: {code} ({detail})"
        if self._on_failure is GateFailureMode.RECOVER:
            return PostflightDecision(
                kind=DecisionKind.RECOVER,
                interceptor_id=self._id,
                reason=reason,
                recovery_hint=RecoveryHint(
                    interceptor_id=self._id,
                    code=code,
                    detail=detail,
                    suggested_action=(
                        suggestions[0] if suggestions else "revise output to satisfy validation"
                    ),
                ),
            )
        return PostflightDecision(
            kind=DecisionKind.REJECT,
            interceptor_id=self._id,
            reason=reason,
        )
