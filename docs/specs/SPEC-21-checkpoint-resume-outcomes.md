---
title: Checkpoint Resume Keeps Node Outcomes
spec_id: SPEC-21
status: Implemented
last_reviewed: 2026-11-06
owner: drchinca
parent: none
depends_on: []
---

# SPEC-21: Checkpoint Resume Keeps Node Outcomes

> A resumed run must see each completed node exactly as it ended — a node that
> failed before the checkpoint stays failed after resume.

## 1. Context

`DAGExecutor` saves a `DAGCheckpoint` after nodes complete, and `resume()`
rebuilds the `completed` map from `completed_nodes`. Every rebuilt node was
marked `success=True`. A node can complete without succeeding and the run still
carries on: a node with `retry_on_failure=True` that fails every attempt, or a
PARALLEL child steered off its write (SPEC-12 §2.4). After resume, such a node
looked successful, so its `ON_SUCCESS` edges fired and its `ON_FAILURE` edges
did not — the resumed run took a different path than the original.

## 2. Interface Contract (MDE)

```python
@dataclass(frozen=True)
class DAGCheckpoint:
    completed_nodes: tuple[NodeID, ...] = ()
    unsuccessful_nodes: tuple[NodeID, ...] = ()   # new: completed, but the result was not a success

# FileCheckpointer JSON gains "unsuccessful_nodes": [str, ...]; a missing field reads as ().
```

## 3. Invariants (DbC)

1. `WHEN a checkpoint is saved, THE System SHALL list in unsuccessful_nodes every completed node whose result was not a success.`
2. `WHEN a run is resumed, THE System SHALL rebuild each completed node with success=False if it is in unsuccessful_nodes, and success=True otherwise.`
3. `unsuccessful_nodes SHALL survive a FileCheckpointer save and load unchanged.`
4. `failed_node keeps its meaning`: it is re-run on resume, whatever `unsuccessful_nodes` says.
5. `THE System SHALL set failed_node only for a failure that ends the run`; a failure that lets the run continue is recorded in `unsuccessful_nodes` alone, so resume treats it the same whenever the process stopped.
6. `Every checkpoint save SHALL describe the run's whole completed map`, including nodes restored from an earlier checkpoint (the exception path included).

Budget: 6 invariants.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Resume keeps node outcomes

  Scenario: A failed node that let the run continue stays failed after resume
    Given a DAG where "broken" (retry_on_failure=True) fails and the run continues
    And "after_broken" needs "broken" to succeed and "flaky" to finish
    And "flaky" fails on its first attempt, so the run stops and is checkpointed
    When the run is resumed and "flaky" succeeds
    Then "after_broken" does not run

  Scenario: Checkpoint files keep unsuccessful nodes
    Given a DAGCheckpoint with unsuccessful_nodes ("second",)
    When it is written and read back through FileCheckpointer serialization
    Then unsuccessful_nodes is ("second",)
```

## 5. Out of Scope

- Restoring each node's full `NodeResult` (output, error, metadata) on resume —
  only the success flag is preserved.
- The legacy `CheckpointingDAGExecutor` wrapper in `checkpointer.py`, which does
  not use the native resume path or evaluate edge conditions. Checkpoints it
  writes carry no `unsuccessful_nodes`, so `DAGExecutor.resume` would treat their
  failed nodes as successful.
- Saving a checkpoint on cancellation and on budget/quality halts (with
  `checkpoint_interval > 1` the last saved checkpoint can lag the run).

## 6. Dependencies

- `cemaf.orchestration.checkpointer.DAGCheckpoint`,
  `cemaf.orchestration.file_checkpointer`, `DAGExecutor.resume`.

## 10. Test Coverage Update

- **Integration** (`tests/integration/test_runtime_services_durable_resume.py`):
  the §4 resume scenario through a real `DAGExecutor` and `FileCheckpointer`.
- **Unit** (`tests/unit/test_file_checkpointer.py`): the round-trip scenario.
