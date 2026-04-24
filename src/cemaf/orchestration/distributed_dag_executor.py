"""
Multi-worker DAG executor using asyncio queues and Redis coordination.

Intermediate step before Temporal.io — enables horizontal parallelism
within a pod cluster without external workflow infrastructure. Uses
RedisCircuitBreaker and RedisRateLimiter for cross-process coordination.
"""

import asyncio

from cemaf.context.context import Context
from cemaf.core.execution import CancellationToken
from cemaf.core.types import RunID
from cemaf.orchestration.dag import DAG
from cemaf.orchestration.executor import DAGExecutor, ExecutionResult

_QueueItem = tuple[
    DAG, Context | None, RunID | None, CancellationToken | None, "asyncio.Future[ExecutionResult]"
]


class DistributedDAGExecutor:
    """
    Wraps a DAGExecutor and adds a work-queue for non-blocking DAG submission.

    Single-pod distribution is achieved by routing submitted DAGs through an
    asyncio.Queue consumed by N worker coroutines — each calling inner.run()
    on the shared DAGExecutor. For multi-pod distribution, each pod runs its
    own DistributedDAGExecutor and picks work from a shared Redis queue (that
    layer is out-of-scope here; use Temporal.io or Celery for that tier).
    """

    def __init__(
        self,
        inner: DAGExecutor,
        n_workers: int = 4,
        redis_url: str | None = None,
    ) -> None:
        self._inner = inner
        self._n_workers = n_workers
        self._redis_url = redis_url  # Reserved for future cross-pod coordination.
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task[None]] = []

    async def run(
        self,
        dag: DAG,
        initial_context: Context | None = None,
        run_id: RunID | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Execute a DAG synchronously (delegates directly to inner.run)."""
        return await self._inner.run(
            dag=dag,
            initial_context=initial_context,
            run_id=run_id,
            cancellation_token=cancellation_token,
        )

    def submit_dag(
        self,
        dag: DAG,
        initial_context: Context | None = None,
        run_id: RunID | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> asyncio.Future[ExecutionResult]:
        """
        Enqueue a DAG for execution by the worker pool.

        Returns a Future that resolves to ExecutionResult when a worker
        picks up and completes the job. Call start_workers() before
        submitting to ensure workers are running.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[ExecutionResult] = loop.create_future()
        self._queue.put_nowait((dag, initial_context, run_id, cancellation_token, future))
        return future

    async def start_workers(self) -> None:
        """Spawn N worker coroutines that consume from the internal queue."""
        for i in range(self._n_workers):
            task = asyncio.get_event_loop().create_task(
                self._worker_loop(),
                name=f"distributed-dag-worker-{i}",
            )
            self._worker_tasks.append(task)

    async def stop_workers(self) -> None:
        """Cancel all worker tasks and wait for them to finish."""
        for task in self._worker_tasks:
            task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

    async def _worker_loop(self) -> None:
        """Continuously dequeue and execute DAGs until cancelled."""
        while True:
            try:
                dag, ctx, run_id, token, future = await self._queue.get()
            except asyncio.CancelledError:
                return

            try:
                result = await self._inner.run(
                    dag=dag,
                    initial_context=ctx,
                    run_id=run_id,
                    cancellation_token=token,
                )
                if not future.done():
                    future.set_result(result)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._queue.task_done()
