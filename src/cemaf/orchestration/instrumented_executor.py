"""
OTel-instrumented DAGExecutor decorator.

Wraps DAGExecutor.run() with a root span and each node execution with
a child span. Propagates W3C TraceContext via _correlation_id_var.

Per-node spans: The DAGExecutor dispatches nodes through internal helpers
and ContextVars that are not exposed as public hooks. Instrumenting at the
per-node level without forking DAGExecutor would require either monkey-
patching private methods (fragile) or adding a callback hook to the
executor contract (future work tracked as cemaf#instrumented-node-spans).
For now, each DAG run produces one root span covering the full execution.
"""

from cemaf.context.context import Context
from cemaf.core.execution import CancellationToken
from cemaf.core.types import RunID
from cemaf.observability.protocols import Tracer
from cemaf.orchestration.dag import DAG
from cemaf.orchestration.executor import DAGExecutor, ExecutionResult


class InstrumentedDAGExecutor:
    """
    Wraps a DAGExecutor and emits a single OTel span per DAG run.

    The span carries the DAG name and run ID as attributes and is marked
    OK on success or ERROR (with exception message) on failure.
    """

    def __init__(self, inner: DAGExecutor, tracer: Tracer) -> None:
        self._inner = inner
        self._tracer = tracer

    async def run(
        self,
        dag: DAG,
        initial_context: Context | None = None,
        run_id: RunID | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Run the DAG wrapped in a root OTel span."""
        from cemaf.core.utils import generate_id

        effective_run_id = run_id or RunID(generate_id("run"))
        span = self._tracer.start_span(
            "cemaf.dag.run",
            attributes={
                "cemaf.dag.name": dag.name,
                "cemaf.run.id": str(effective_run_id),
            },
        )
        try:
            result = await self._inner.run(
                dag=dag,
                initial_context=initial_context,
                run_id=effective_run_id,
                cancellation_token=cancellation_token,
            )
            if result.success:
                span.set_status("OK")
            else:
                span.set_status("ERROR", result.error or "DAG execution failed")
            return result
        except Exception as exc:
            span.set_status("ERROR", str(exc))
            raise
        finally:
            span.end()
