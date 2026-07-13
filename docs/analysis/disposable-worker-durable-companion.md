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

Run the destructive red-team profile:

```bash
uv run python benchmarks/red_team_durable_companion.py
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
| Exclusive ownership | `FileRunLeaseStore`, `RunLease`, `FencedCheckpointer` | Durable companion root |
| Exactly-once local effect | `FileIdempotentEffectSink` | Idempotent destination keyed by workflow run |

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
| Idempotent effect receipts | 1,000 |
| Elapsed time after durability hardening | 12,349.357 ms |
| Throughput after durability hardening | 80.98 pipelines/s |

The correctness counts are the acceptance criteria; throughput is supporting
evidence only. This is a controlled positive profile, not the final durability
verdict.

## Destructive Red-Team Result

The red-team harness uses actual subprocesses, sends `SIGKILL` to the active
worker, reloads state from disk, races two replacement processes against the
same run, and injects process loss during checkpoint and trace overwrites.

| Invariant | Result | Evidence |
|---|---|---|
| One owner: OS-killed worker can be replaced | **SURVIVED** | Process exited `-9`; checkpoint retained `ingest`; replacement completed with one external effect. |
| Completed attempt trace reloads and replays | **SURVIVED** | `RunRecord.from_dict` + patch-only replay matched the persisted final context. |
| Duplicate resume is exactly-once | **SURVIVED** | One replacement acquired the durable lease; the other was rejected. One effect receipt was created. |
| Interrupted checkpoint overwrite preserves last good state | **SURVIVED** | The atomic replacement failed before commit and the previous checkpoint remained parseable. |
| Interrupted trace overwrite preserves last good trace | **SURVIVED** | The atomic replacement failed before commit and the previous live trace remained parseable. |
| Interrupted effect write is retryable and exactly-once | **SURVIVED** | No partial receipt became visible; retry created one durable effect. |

Current local-backend red-team verdict: **SURVIVED** with no broken invariants.
This supersedes the earlier broken result that motivated the hardening work.

## Proven Boundary And Remaining Production Work

This proves restart recovery, exclusive takeover, fencing, crash-consistent
replacement, and an idempotent local effect destination for two or three
concurrent workers on a POSIX host or POSIX-compatible shared filesystem.

For multi-process or multi-host deployment, keep the same `Checkpointer`,
`RunLogger`, and `EventBus` protocol boundaries and replace the local backends
with transactional shared storage implementing the same lease and checkpointer
contracts. CEMAF already provides the durable Redis Streams `RedisEventBus`;
production database/cloud adapters remain deployment responsibilities, not
agent responsibilities.

The hardening implemented after the first red-team failure is:

1. Atomic checkpoint and trace replacement: write a temporary file, flush and
   `fsync`, atomically rename, then sync the parent directory while retaining a
   previous generation.
2. A durable run lease with monotonic fencing tokens; stale checkpoint writes
   are rejected even if validation raced with takeover.
3. An idempotent effect-sink protocol and crash-safe local destination. External
   adapters must propagate the key to their destination or use an outbox.

Automated recovery detection and scheduling remain deployment composition: the
framework now makes takeover safe, but does not run a permanent supervisor.

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
