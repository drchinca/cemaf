# SPEC-15 — Memory branches with a merge review gate

> Status: Draft · Last-Reviewed: 2026-07-04 · Depends on: SPEC-00, SPEC-12
> Owns: a small set of protocols that let concurrent agents write memory on
> isolated branches and go through a reviewable merge gate before those writes
> reach shared scope. **No branch storage engine, no merge algorithm.** CEMAF
> exposes the shape; graph databases, KG stores, or in-house adapters provide
> the mechanics.

## 1. Context

Concurrent agents writing to the same memory keys today rely on
`collision/` — a TCAS-style **pre-write advisory** (`Advisory` bands
CLEAR/TA/RA in `src/cemaf/collision/`). That checkpoint runs *before* a
write and gives right-of-way. It does not model the case where two agents
have both written their own version of the same fact and a human or
policy has to reconcile them.

Durable graph and knowledge substrates surface a second, complementary
checkpoint: **branch-per-agent with merge-on-review.** Each agent writes on
an isolated branch of the memory space, and promotion of those writes to
shared scope requires a merge step that can detect conflicts, apply a
strategy, or defer to a reviewer.

CEMAF is not a graph database and will not implement branch storage. This
spec proposes the two protocols an external substrate would satisfy so
that CEMAF's `MemoryManager` and shared context can plug into a branchable
backend without the executor caring which one.

## 2. Interface Contract (MDE)

Both protocols live in `cemaf.memory.branch` (new module). They are
`@runtime_checkable` and vendor-neutral.

```python
BranchID = NewType("BranchID", str)

@dataclass(frozen=True, slots=True)
class MemoryBranchRef:
    id: BranchID
    parent_id: BranchID | None
    agent_id: str                    # who owns writes on this branch
    scope: MemoryScope               # SESSION / PROJECT / GLOBAL
    metadata: JSON

@runtime_checkable
class MemoryBranch(Protocol):
    async def open(
        self,
        *,
        agent_id: str,
        scope: MemoryScope,
        parent: BranchID | None = None,
    ) -> MemoryBranchRef: ...

    async def write(self, *, branch: BranchID, item: MemoryItem) -> None: ...
    async def read(self, *, branch: BranchID, key: str) -> MemoryItem | None: ...
    async def list(self, *, branch: BranchID) -> tuple[MemoryItem, ...]: ...
    async def close(self, *, branch: BranchID) -> None: ...

@dataclass(frozen=True, slots=True)
class MergeConflict:
    key: str                       # memory key at the point of conflict
    left: MemoryItem               # value on the incoming branch
    right: MemoryItem              # value on the target branch
    strategy_hint: str | None      # e.g. "prefer_higher_score", "last_write_wins"

@dataclass(frozen=True, slots=True)
class MergeReviewResult:
    branch: BranchID
    target: BranchID               # branch merged into (or main-of-scope)
    merged: bool
    conflicts: tuple[MergeConflict, ...]
    metadata: JSON

@runtime_checkable
class MergeReview(Protocol):
    """Post-write gate. `propose` inspects an incoming branch and either
    reports conflicts (caller resolves) or applies the merge under the
    supplied strategy."""

    async def propose(
        self,
        *,
        branch: BranchID,
        target: BranchID,
        strategy: MergeStrategyRef,
    ) -> MergeReviewResult: ...
```

`MemoryScope` is CEMAF's existing enum (`cemaf.core.enums.MemoryScope`).
`MemoryItem` is unchanged. `MergeStrategy` reuses the vocabulary that
already exists in `cemaf.context.merge` — `LastWriteWinsStrategy`,
`RaiseOnConflictStrategy`, `DeepMergeStrategy`, `ReducerMergeStrategy`.
`MergeStrategyRef` is a discriminator string (`"last_write_wins"`,
`"deep_merge"`) or a callable adapter; **memory branches do not invent a
second merge vocabulary.**

## 3. Invariants (DbC)

1. A branch is owned by exactly one `agent_id` for the duration of its lifetime.
2. Writes on branch `b` are invisible to reads on branches other than `b` and its descendants until a `MergeReview` completes with `merged=True`.
3. `open(parent=None)` on scope `S` returns a branch rooted at the main-of-scope; the main-of-scope itself is not writable through the branch API — only through merges.
4. `MergeReviewResult.conflicts` is empty **iff** `merged is True`.
5. `MergeReview` never applies a merge with a strategy CEMAF's `cemaf.context.merge` vocabulary does not name.
6. `close(branch=b)` is idempotent; reads on `b` after close return `None`.
7. `MemoryBranch` implementations MUST NOT mutate `MemoryItem` values in place — writes are copy-on-branch.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Memory branches with merge review

  Scenario: Two agents write conflicting values on separate branches
    Given branch B_a opened by agent_a on PROJECT scope
    And branch B_b opened by agent_b on PROJECT scope
    When agent_a writes key "hypothesis" with value "H1" on B_a
    And agent_b writes key "hypothesis" with value "H2" on B_b
    Then a read of "hypothesis" from B_a returns "H1"
    And a read of "hypothesis" from B_b returns "H2"
    And a read of "hypothesis" from main-of-PROJECT returns None

  Scenario: Merge review surfaces a conflict when strategy demands it
    Given B_a written above
    And B_b written above
    When MergeReview.propose(branch=B_a, target=main, strategy=raise_on_conflict) runs first
    Then the result has merged=True and no conflicts
    When MergeReview.propose(branch=B_b, target=main, strategy=raise_on_conflict) runs next
    Then the result has merged=False and one MergeConflict for key "hypothesis"

  Scenario: Merge review resolves under last_write_wins
    Given the state above
    When MergeReview.propose(branch=B_b, target=main, strategy=last_write_wins) runs
    Then the result has merged=True
    And a read of "hypothesis" from main-of-PROJECT returns "H2"
```

## 5. Out of scope

- **Branch storage engine.** No append-only log, no CoW file layout, no
  time-travel query surface. Every implementation adapter is free to
  provide any of that; CEMAF core stays branch-storage-agnostic.
- **Concurrency control.** Advisory / write coordination stays with
  `collision/`. This spec's gate is a **second checkpoint**, not a
  replacement.
- **Cross-scope merges.** SESSION → PROJECT promotion already exists in
  the extraction pipeline; a branch cannot straddle scopes.
- **Automatic reviewer selection.** How a human or policy is asked to
  resolve conflicts is a caller concern.

## 6. Dependencies

- SPEC-00 §*Memory* — scope semantics.
- SPEC-12 (agent collision avoidance) — pre-write advisory checkpoint;
  this spec's gate runs *after* that one.
- `cemaf.context.merge` — merge strategy vocabulary reused verbatim.

## 7. Correctness Properties

### Property 1: Isolation

*For any two branches* `B_x, B_y` *neither of which is an ancestor of the
other, a write on `B_x` is not observable by a reader on `B_y` before a
successful `MergeReview` on `B_x`.*

**Validates: §3 Invariant 2, §4 Scenario "Two agents write conflicting values"**

### Property 2: Strategy fidelity

*For any `MergeReview.propose(strategy=S)` that returns `merged=True`, the
resulting state on `target` is identical to the state produced by applying
`S`'s existing implementation in `cemaf.context.merge` to the pair of
inputs.*

**Validates: §3 Invariant 5, §4 Scenario "Merge review resolves under last_write_wins"**

## 10. Test Coverage Update

- **L0**: contract tests over `MemoryBranch.open/write/read/close`
  round-trip using the default adapter, one test per §2 method.
- **L1**: routing test — a caller opens branches for two agents in
  parallel, both writes land, reads on each branch see only their own.
- **L2**: `MergeReview.propose` under each named strategy; invariant
  checks (Property 1 + 2); a conflict is reported when
  `raise_on_conflict` sees divergent values.
- **e2e**: a real `MemoryManager` wired to the default in-memory branch
  adapter drives the §4 Gherkin scenarios end-to-end.

## Non-obligation to implement

This spec is **shape-only**. A default in-memory adapter that satisfies
§2 and passes §10 is required before any consumer wires branches. Any
substrate adapter (graph DB, lakehouse, in-house store) supplying its own
branch mechanics MUST pass the same §10 corpus without CEMAF changes.
