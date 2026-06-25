# cemaf.state

Typed, persisted, observable state machines as a first-class CEMAF primitive.

Use whenever you need a finite state machine with:

- Compile-time-checked states + events (StrEnum)
- Persisted state across runs (any `FsmStore` impl — in-memory ships, Postgres / SQLite plug in)
- Append-only history with `correlation_id` provenance
- Optimistic locking on concurrent writes
- Optional human-in-the-loop gates (`requires_hitl=True`) that reject non-human actors
- Optional async guards + handlers per transition (handlers compose with `cemaf.orchestration.DAGExecutor`)
- Mermaid topology rendering for docs and dashboards

## Minimal example

```python
from enum import StrEnum
from cemaf.state import StateMachine, Transition, InMemoryFsmStore


class TrafficLight(StrEnum):
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"


class TrafficEvent(StrEnum):
    GO = "go"
    SLOW = "slow"
    STOP = "stop"


fsm = StateMachine[TrafficLight, TrafficEvent](
    kind="traffic_light",
    states=TrafficLight,
    events=TrafficEvent,
    transitions=[
        Transition(from_state=TrafficLight.RED,    event=TrafficEvent.GO,   to_state=TrafficLight.GREEN),
        Transition(from_state=TrafficLight.GREEN,  event=TrafficEvent.SLOW, to_state=TrafficLight.YELLOW),
        Transition(from_state=TrafficLight.YELLOW, event=TrafficEvent.STOP, to_state=TrafficLight.RED),
    ],
    store=InMemoryFsmStore(),
    initial_state=TrafficLight.RED,
)

await fsm.create(fsm_id="intersection-42")
await fsm.fire(
    fsm_id="intersection-42",
    event=TrafficEvent.GO,
    actor="controller",
    actor_kind="agent",
    correlation_id="run_abc",
)
```

## What this primitive is NOT

- A workflow engine — use `cemaf.orchestration.DAGExecutor` for that. Transition handlers MAY dispatch DAGs.
- A scheduler — there are no timers / cron / "auto-fire after N minutes" hooks. Use `cemaf.scheduler` to drive `fsm.fire()` from outside.
- A distributed FSM — single-process. Persistence comes from `FsmStore`; horizontal scale is the store's responsibility.

## Public API

| Symbol | Purpose |
|--------|---------|
| `StateMachine[StateT, EventT]` | The FSM |
| `Transition[StateT, EventT]` | A single allowed transition with optional guard / handler / HITL flag |
| `FsmState` | Persisted state record |
| `StateTransition` | Append-only audit row |
| `FsmStore` | Storage protocol — bring your own |
| `InMemoryFsmStore` | Reference impl, async-safe within a single process |
| `fsm_store_registry` | Register custom `FsmStore` backends |
| `create_fsm_store()` | Create an FSM store by backend name |
| `TransitionNotAllowed` | No matching transition, or current state is terminal |
| `GuardRejected` | Guard returned False (or raised) |
| `HitlRequired` | Transition needs a human actor and got an agent |
| `HandlerFailed` | Handler raised; new state was not persisted |
| `VersionConflict` | Optimistic-locking collision on concurrent fires |

## Store factories

The built-in `memory` backend is intentionally small. Register durable stores at the composition root:

```python
from cemaf.state import FsmStore, create_fsm_store, fsm_store_registry


def create_postgres_fsm_store(**options) -> FsmStore:
    return PostgresFsmStore(dsn=options["dsn"])


fsm_store_registry.register(
    backend="postgres",
    factory=create_postgres_fsm_store,
)

store = create_fsm_store(backend="postgres", dsn="postgresql://...")
```

## Invariants

1. Typed states + events (StrEnum); plain strings rejected by the type system.
2. Explicit transitions only — duplicate `(from_state, event)` rejected at construction; no fallthrough.
3. Optimistic locking via `FsmStore.save(expected_version=...)`.
4. HITL non-bypass — `requires_hitl=True` rejects `actor_kind != "human"` before guard / handler.
5. Append-only history — every successful fire appends; entries never edited or deleted via the public API.
6. Handler failure rolls back — new state never persisted on handler exception.
7. Terminal states absorb — `fire()` on a terminal state always raises `TransitionNotAllowed`.
8. Provenance — `correlation_id` required on every fire and propagated to history + handler.
9. No global state — instances created per FSM kind via DI; no module-level defaults.

See `tests/state/test_fsm.py` for the full Gherkin-equivalent test surface.
