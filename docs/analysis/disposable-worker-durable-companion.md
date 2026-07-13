# Disposable Workers With A Durable Companion Service Plane

This executable proof tests a strict ownership boundary:

- A pipeline executor is a disposable worker. Losing it must not lose lineage,
  checkpoints, recovery state, or trace evidence.
- Durable authority lives in companion services reachable by replacement
  workers. The companion is not an agent and does not choose or execute DAG
  steps on the hot path.

Run the app-shape proof:

```bash
uv run python examples/app_shapes/disposable_workers_durable_companion.py
```

Run the load profile:

```bash
uv run python benchmarks/stress_disposable_workers.py --runs 1000 --workers 3
```

## CEMAF Composition

| Concern | CEMAF primitive | Ownership in the proof |
|---|---|---|
| Flow | `DAG`, `Node`, `Edge`, `DAGExecutor` | Disposable worker |
| Checkpoints and resume | `CheckpointingDAGExecutor`, `FileCheckpointer` | Durable companion root |
| Lineage | Immutable `Context` and `ContextPatch` history | Durable checkpoint |
| Healing | `AutoHealManager`, `RecoveryStrategy` | Companion recovery policy injected through `RuntimeServices` |
| Attempt tracing | `FileRunLogger`, `RunRecord` | Durable companion root |
| Replay | `Replayer(PATCH_ONLY)` | Companion read path after workers are gone |

The test terminates every first-attempt worker with `CancelledError` immediately
before the second node. The first node has already been checkpointed. It then
constructs a new `DurableCompanion` and a new worker from only the filesystem
root, resumes the pending nodes, injects a transient publish error, heals it,
and verifies deterministic replay against the completed checkpoint.

## Stress Result

Local run on 2026-07-13:

| Measure | Result |
|---|---:|
| Concurrent workers | 3 |
| Pipelines | 1,000 |
| Forced worker terminations | 1,000 |
| Replacement-worker completions | 1,000 |
| Healed runs | 1,000 |
| Replay matches | 1,000 |
| Durable checkpoint files | 1,000 |
| Durable attempt-trace directories | 2,000 |
| Abandoned dead-worker traces retained | 1,000 |
| Unique lineage patches | 4,000 / 4,000 |
| Elapsed time | 2,076.605 ms |
| Throughput | 481.56 pipelines/s |

The correctness counts are the acceptance criteria; throughput is supporting
evidence only.

## Proven Boundary And Remaining Production Work

This proves the architecture for two or three concurrent workers on one host or
a shared filesystem, with one active owner per run ID. It does not claim that a
local JSON file is a multi-region control plane.

For multi-process or multi-host deployment, keep the same `Checkpointer`,
`RunLogger`, and `EventBus` protocol boundaries and replace the local backends
with transactional shared storage. Add a lease/claim protocol before allowing
two workers to resume the same run concurrently. CEMAF already provides the
durable Redis Streams `RedisEventBus`; a production shared checkpointer and
run-claim implementation remain deployment adapters, not agent responsibilities.

## Pre-Rewrite Checklist

1. `orchestration`, `context`, `observability`, `replay`, and `core.recovery`
   already own the required concerns.
2. The proof uses their public DAG, service, checkpoint, run-record, and replay
   contracts rather than defining a second orchestration loop or trace format.
3. Cross-cutting healing and tracing are injected through `RuntimeServices`;
   checkpoint storage is supplied through the `Checkpointer` protocol.
4. Only domain work, worker-loss injection, and the companion composition root
   live in the example.
5. `test_disposable_workers_durable_companion.py` runs 60 three-worker pipelines
   and a second two-worker shape, asserting completion, healing, checkpoint,
   lineage, abandoned-trace, and replay invariants.
