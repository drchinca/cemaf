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
| Duplicate resume is exactly-once | **BROKEN** | Both replacement processes completed and the external publish side effect occurred twice. |
| Interrupted checkpoint overwrite preserves last good state | **BROKEN** | Partial write destroyed the previous parseable checkpoint. |
| Interrupted trace overwrite preserves last good trace | **BROKEN** | Partial write destroyed the previous parseable live trace. |

Overall strong durability verdict: **BROKEN**. The 1,000-run green profile is
valid only under its single-owner, uninterrupted-write assumptions.

## Proven Boundary And Remaining Production Work

This proves restart recovery for two or three concurrent workers on one host or
a shared filesystem only when each run has one active owner and storage writes
finish. It does not prove safe concurrent takeover or crash-consistent local
storage.

For multi-process or multi-host deployment, keep the same `Checkpointer`,
`RunLogger`, and `EventBus` protocol boundaries and replace the local backends
with transactional shared storage. Add a lease/claim protocol before allowing
two workers to resume the same run concurrently. CEMAF already provides the
durable Redis Streams `RedisEventBus`; a production shared checkpointer and
run-claim implementation remain deployment adapters, not agent responsibilities.

The concrete hardening requirements exposed by the test are:

1. Atomic checkpoint and trace replacement: write a temporary file, flush and
   `fsync`, atomically rename, then sync the parent directory while retaining a
   previous generation.
2. A durable run lease with fencing tokens so a stale worker cannot checkpoint
   or publish after another worker takes ownership.
3. Idempotency keys or a transactional outbox for external effects. A lease by
   itself cannot guarantee exactly-once behavior across a crash between publish
   and checkpoint.
4. Durable recovery detection/claiming outside application harness code.

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
