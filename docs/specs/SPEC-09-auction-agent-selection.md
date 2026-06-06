---
title: Auction-Based Agent Selection
spec_id: SPEC-09
status: Draft
last_reviewed: 2026-06-06
owner: drchinca
parent: SPEC-00 — Enterprise Context Brain
depends_on: []
---

# SPEC-09: Auction-Based Agent Selection

> Agent selection today is static: a node names one agent by `ref_id` at
> DAG-build time. This spec adds an **opt-in** path where multiple agents
> compete for a node by *capability*, *load*, and *remaining budget*, and a
> deterministic selector picks the winner. The static path remains the
> default — existing DAGs are unchanged.

**Status: Draft.** Implementation target: `cemaf/agents/selection.py`,
`cemaf/agents/registry.py`, `cemaf/orchestration/{dag,context_node_executor,services}.py`,
`cemaf/bootstrap.py`, `cemaf/llm/model_router.py`.

## Contents

- [1. Context](#1-context)
- [2. Interface Contract (MDE)](#2-interface-contract-mde)
- [3. Invariants (DbC)](#3-invariants-dbc)
- [4. Acceptance Criteria (BDD)](#4-acceptance-criteria-bdd)
- [5. Out of Scope](#5-out-of-scope)
- [6. Dependencies](#6-dependencies)
- [7. Correctness Properties](#7-correctness-properties)
- [9. Observability Contract](#9-observability-contract)

## 1. Context

`ContextNodeExecutor.execute_node` resolves an agent by `node.ref_id`
(`context_node_executor.py:72-93`) — one agent per node, bound when the DAG is
authored. There is no notion of agent capability, load, or budget-awareness in
selection. Separately, `ModelRouter` is handed `fidelity` and `token_budget` and
**discards them** (`model_router.py:118` — `del fidelity, token_budget,
correlation_id`), routing purely on a char-count complexity estimate.

This is the one mechanism from the axocoatl comparison audit that is a genuine
gap *and* one CEMAF is positioned to ship cheaply: `BudgetGuard` already exposes
`cost_utilization` / `token_utilization` (`budget_guard.py:46-116`), and the
registry already indexes agents. An auction is: let N agents bid on a node,
score by (capability match, load, budget headroom), run the highest bidder.

```mermaid
sequenceDiagram
    participant N as Node (auction, capability=WRITE)
    participant E as ContextNodeExecutor
    participant R as AgentRegistry
    participant S as AgentSelector

    E->>R: get_candidates(WRITE)
    R-->>E: (agent_a, agent_b, ...)
    E->>S: select(candidates, BidContext{cap, goal_text, budget util})
    S-->>E: Bid{agent_id, score, ...}   (highest, deterministic tie-break)
    E->>E: resolve agent_id → run; record Bid in NodeResult.metadata["selection"]
```

The selection is a **pure, deterministic** function of its inputs — no I/O, no
randomness — so a run is replayable and the choice is auditable.

## 2. Interface Contract (MDE)

New module `cemaf/agents/selection.py`:

```python
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from cemaf.agents.protocols import Agent
from cemaf.core.types import JSON, AgentID

_DEFAULT_LOAD = 0.5
_DEFAULT_MATCH = 0.3
_FIDELITY_FLOOR: dict["Fidelity", float] = {}   # {LOW: 0.0, STANDARD: 0.4, HIGH: 0.8}


class Capability(StrEnum):
    RESEARCH = "research"
    SUMMARIZE = "summarize"
    WRITE = "write"
    LIBRARY = "library"
    QUALITY = "quality"


class Fidelity(StrEnum):
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class BidContext:
    capability: Capability
    goal_text: str = ""
    cost_utilization: float = 0.0      # BudgetGuard.cost_utilization, 0.0 if absent
    token_utilization: float = 0.0     # BudgetGuard.token_utilization, 0.0 if absent


@dataclass(frozen=True, slots=True)
class Bid:
    agent_id: AgentID
    score: float                        # in [0.0, 1.0]; higher wins
    capability_match: float             # in [0.0, 1.0]
    load_factor: float                  # 1 - current_load, in [0.0, 1.0]
    budget_headroom: float              # 1 - max(cost_util, token_util), in [0.0, 1.0]

    def to_metadata(self) -> JSON:
        """Provenance projection stored on NodeResult.metadata['selection'].

        Keys: agent_id (str), score, capability_match, load_factor, budget_headroom.
        """
        ...


@runtime_checkable
class CapabilityAdvertiser(Protocol):
    """OPTIONAL protocol an Agent MAY implement. Non-advertisers get default scoring."""

    @property
    def capabilities(self) -> frozenset[Capability]: ...

    @property
    def current_load(self) -> float: ...   # 0.0 idle … 1.0 saturated


@runtime_checkable
class AgentSelector(Protocol):
    """BYO-X seam — swap the scoring policy. DefaultAgentSelector is the default."""

    def select(
        self,
        *,
        candidates: tuple[Agent[Any, Any], ...],
        bid_context: BidContext,
    ) -> Bid | None: ...


class DefaultAgentSelector:
    """Deterministic single-round max-bid selector."""

    def bid_for(self, *, agent: Agent[Any, Any], bid_context: BidContext) -> Bid: ...

    def select(
        self, *, candidates: tuple[Agent[Any, Any], ...], bid_context: BidContext
    ) -> Bid | None: ...


def create_default_agent_selector() -> DefaultAgentSelector:
    """Factory (BYO-X) — wired into RuntimeServices.agent_selector at bootstrap."""
    ...
```

**Reading an agent's capability/load (the detection rule).** `isinstance(agent,
CapabilityAdvertiser)` on a `@runtime_checkable` protocol only verifies that the
`capabilities` and `current_load` *attributes exist* — not that they return the
right types (PEP 544). The selector therefore **duck-types defensively**, never
trusting `isinstance` as a behavioral gate:

```python
def _read_capabilities(agent: Agent[Any, Any]) -> frozenset[Capability] | None:
    raw = getattr(agent, "capabilities", None)
    if not isinstance(raw, frozenset):
        return None
    return frozenset(c for c in raw if isinstance(c, Capability))

def _read_load(agent: Agent[Any, Any]) -> float:
    raw = getattr(agent, "current_load", None)
    if not isinstance(raw, int | float):
        return _DEFAULT_LOAD          # 0.5
    return min(1.0, max(0.0, float(raw)))   # clamp to [0,1] — load is self-reported, untrusted
```

A non-advertiser (or a malformed one) yields `capabilities=None` → `match=0.3`
and `load=0.5`.

Registry additions (`registry.py`):

```python
# new index alongside _domain_agents
self._capability_agents: dict[Capability, set[str]] = {}

# built-in agent → capabilities, alongside _BUILTIN_GOAL_TYPES (module level)
_BUILTIN_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "Librarian": frozenset({Capability.LIBRARY}),
    "Researcher": frozenset({Capability.RESEARCH}),
    "Summarizer": frozenset({Capability.SUMMARIZE}),
    "Writer": frozenset({Capability.WRITE}),
    "QualityGuard": frozenset({Capability.QUALITY}),
}

def register_agent(
    self,
    agent_instance: Agent[Any, Any],
    goal_type: type[BaseModel] | None = None,
    domain_id: str | None = None,
    capabilities: frozenset[Capability] | None = None,   # NEW, optional
) -> None: ...

def get_candidates(self, *, capability: Capability) -> list[Agent[Any, Any]]: ...
```

**Capability source reconciliation (single source of truth).** Two inputs could
declare an agent's capabilities — the explicit `capabilities=` kwarg at
registration and an agent that implements `CapabilityAdvertiser`. The registry
index `_capability_agents` is the **authoritative candidate set**, populated at
`register_agent` from, in precedence order: (1) the explicit `capabilities=`
kwarg, else (2) the agent's advertised `capabilities` (duck-typed read), else
(3) `_BUILTIN_CAPABILITIES` for known built-in names. `get_candidates` reads only
this index. The selector's per-bid `capability_match` then re-reads the agent's
advertised capabilities — so a candidate that is in the index but does not
advertise the exact capability still scores the 0.3 generalist match (never a
silent disagreement: index = "who may bid", advertiser = "how well they bid").

**Candidate resolvability.** Every agent returned by `get_candidates` MUST be
resolvable back through `registry.get(str(agent.id))` — the executor resolves the
winning `Bid.agent_id` via the existing `self._registry.get(agent_name)` path
(`context_node_executor.py:81`), so `Bid.agent_id == agent.id` is the registry key.

DAG factory (`dag.py`), next to `Node.agent`:

```python
@classmethod
def auction(
    cls,
    id: str,
    name: str,
    capability: Capability,
    description: str = "",
    config: JSON | None = None,
    input_mapping: JSON | None = None,
    output_key: str = "",
) -> Node:
    """Create an AGENT node selected by auction. ref_id stays empty; config carries the capability."""
```

`RuntimeServices` gains `agent_selector: AgentSelector | None = None`.
`ContextNodeExecutor.__init__` gains `agent_selector` + `budget_guard`.

## 3. Invariants (DbC)

1. **Score range (clamped)**: every `Bid.score`, `capability_match`,
   `load_factor`, `budget_headroom` ∈ [0.0, 1.0]. Inputs are clamped before
   scoring — `current_load` and the budget utilizations are each clamped to
   [0,1], so an over-budget `cost_utilization > 1.0` yields `budget_headroom = 0.0`,
   never negative.
2. **Determinism**: `select(candidates, bid_context)` is a pure function — same
   inputs ⇒ identical `Bid`. No randomness, no I/O.
3. **Total ordering**: ties on `score` are broken by `str(agent_id)` so the
   winner is unique and stable.
4. **Default scoring**: an agent that does not implement `CapabilityAdvertiser`
   gets `capability_match = 0.3` (generalist) and `current_load = 0.5`.
   An advertiser whose `capabilities` contains the requested one gets
   `capability_match = 1.0`; an advertiser missing it gets `0.3`.
5. **Scoring formula**: `score = 0.5·capability_match + 0.3·load_factor +
   0.2·budget_headroom`, where `load_factor = 1 − current_load` and
   `budget_headroom = 1 − max(cost_utilization, token_utilization)`.
6. **Opt-in only**: the auction path runs **iff** `node.config["capability"]` is
   set AND an `AgentSelector` is wired. Otherwise `ref_id` static resolution runs
   unchanged.
7. **Fail-safe fallthrough**: if the auction yields no candidates (`select`
   returns `None`), the executor falls through to static `ref_id` resolution; if
   `ref_id` is also empty, it returns the existing "no ref_id" error — never a crash.
8. **Provenance (both branches)**: when an auction selects an agent, the winning
   `Bid` is recorded on `NodeResult.metadata["selection"]` regardless of whether
   the selected agent then succeeds or fails — the selection happened either way.
9. **Fidelity floor (ModelRouter)**: when `fidelity` is provided, the routed
   complexity score is `max(estimator_score, FIDELITY_FLOOR[fidelity])` with floors
   `{LOW: 0.0, STANDARD: 0.4, HIGH: 0.8}`. `token_budget`/`correlation_id` remain
   out of scope.

EARS form (selected):

```
WHEN node.config has a capability AND an AgentSelector is wired, THE System SHALL run the auction.
IF the auction returns no candidates, THEN THE System SHALL fall through to ref_id static resolution.
WHEN an auction selects an agent, THE System SHALL record the winning Bid on NodeResult.metadata["selection"].
WHERE fidelity is provided to ModelRouter, THE System SHALL floor the route score at FIDELITY_FLOOR[fidelity].
```

Budget: 9 invariants — within ≤15.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Auction-based agent selection

  Scenario: Deterministic selection
    Given two candidate agents and a BidContext
    When select() is called twice with identical inputs
    Then both calls return structurally-identical Bids

  Scenario: Capability match beats a generalist
    Given an advertiser agent with capability WRITE and a non-advertiser agent
    And a BidContext requesting WRITE
    When the auction runs
    Then the advertiser wins

  Scenario: Higher load lowers score
    Given two WRITE advertisers with current_load 0.1 and 0.9
    When the auction runs with equal budget
    Then the load-0.1 agent wins

  Scenario: Budget pressure preserves the winner
    Given two candidates that select agent A under no budget pressure
    When the auction runs with cost_utilization 0.95
    Then agent A still wins (the budget term is shared, shifting both equally)

  Scenario: Over-budget utilization clamps headroom to zero
    Given cost_utilization 1.5 (reported over budget)
    When a bid is scored
    Then budget_headroom equals 0.0 and the score stays in [0,1]

  Scenario: Exact-tie resolves by agent id
    Given two candidates with byte-identical scores
    When select() runs
    Then the agent whose str(id) sorts first (desc) is the unique winner

  Scenario: Single candidate still produces a bid
    Given exactly one candidate for the capability
    When the auction runs
    Then that agent wins and metadata["selection"] is recorded

  Scenario: No candidates returns None
    Given a capability with zero registered candidates
    When select() is called with an empty candidates tuple
    Then it returns None

  Scenario: No-candidate auction falls through to static ref_id
    Given an auction node whose capability has no candidates but ref_id="Writer"
    When the node executes
    Then the Writer agent runs via static resolution

  Scenario: No-candidate auction with empty ref_id errors cleanly
    Given an auction node whose capability has no candidates AND ref_id is empty
    When the node executes
    Then it returns the "no ref_id" NodeResult error, not a crash

  Scenario: Capability set but selector not wired falls through to static
    Given an auction node with capability set but no AgentSelector wired
    When the node executes
    Then static ref_id resolution runs (auction path not entered)

  Scenario: Static ref_id node is unaffected by a wired selector
    Given a Node.agent("Writer") and an executor with a DefaultAgentSelector
    When the node executes
    Then Writer runs and no auction is performed

  Scenario: Winning bid is recorded for provenance
    Given an auction selects an agent
    When the node completes
    Then NodeResult.metadata["selection"]["agent_id"] equals the winner

  Scenario: Fidelity floor raises a trivial route
    Given a one-line prompt that scores 0.1 by complexity
    And fidelity HIGH
    When the router scores it
    Then the score is at least 0.8
```

13 scenarios — within ≤20.

> **§8 Eval Criteria omitted** — selection is a deterministic, pure function
> with no LLM behavior to evaluate; §3 invariants + §7 properties (verified by
> example + property-based tests) cover correctness fully. No LLM-judge gate applies.

## 5. Out of Scope

- Sealed-bid / second-price / multi-round auction economics — single-round max.
- New `Node` fields or DAG-schema / serialization changes — reuse `config`.
- Live load telemetry, queues, concurrency tracking — `current_load` is
  self-reported; default 0.5.
- Additions to the core `Agent` protocol — capability/load live on the optional
  `CapabilityAdvertiser`.
- Async selection — scoring is sync/pure.
- Multi-winner, fallback chains, retry-on-loser — pick one, run it.
- `token_budget` / `correlation_id` plumbing in `ModelRouter` — only `fidelity`.
- Bid persistence beyond `NodeResult.metadata`.

## 6. Dependencies

- `cemaf.agents.protocols.Agent`, `cemaf.core.types.AgentID`.
- `cemaf.observability.budget_guard.BudgetGuard` — `cost_utilization`,
  `token_utilization`.
- `cemaf.orchestration.dag.Node` (`config: JSON`), `services.RuntimeServices`.
- `cemaf.llm.model_router.ModelRouter`.

## 7. Correctness Properties

### Property 1: Selection is a deterministic total order

*For any* candidate set `C` and context `X`, `select(C, X)` returns the unique
maximum under the order `(score, str(agent_id))` desc — independent of input
ordering and invocation count.

**Validates: §3 Invariants 2, 3; §4 Scenarios "Deterministic selection",
"Budget pressure preserves ordering"**

### Property 2: Opt-in isolation

*For any* `Node.agent(...)` (no `config["capability"]`), execution resolves the
agent exactly as before regardless of whether an `AgentSelector` is wired — the
auction code path is not entered.

**Validates: §3 Invariants 6, 7; §4 Scenario "Static ref_id node is unaffected"**

### Property 3: Bounded scores

*For any* agent and context, all `Bid` components and the aggregate `score` lie
in [0.0, 1.0].

**Validates: §3 Invariants 1, 5**

## 9. Observability Contract

- **Provenance**: winning `Bid` projected onto `NodeResult.metadata["selection"]`
  = `{agent_id, score, capability_match, load_factor, budget_headroom}`.
- **Log events**:
  - `agent.auction.started` — `node_id`, `capability`, `candidate_count`
  - `agent.auction.selected` — `node_id`, `agent_id`, `score`
  - `agent.auction.no_candidates` — `node_id`, `capability` (fall-through path)
- **Metrics** (Prometheus, optional): `cemaf_agent_auction_total{capability, outcome}`
  where `outcome ∈ {selected, no_candidates}`.

**Fidelity wiring note.** `Fidelity` and `_FIDELITY_FLOOR` live in `selection.py`
for colocation with `Capability`, but the floor is applied in
`model_router.py` (Invariant 9) — `ModelRouter.route` already receives
`fidelity` (today discarded at `model_router.py:118`); the change is to stop
discarding it and floor the estimator score. The auction itself does not consult
fidelity; the two share this spec only because both stop wasting signals the
system already computes.
