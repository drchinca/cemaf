# CEMAF Enhancement Plan: Context Engineering Differentiator

## Strategic Goal

Position CEMAF as **context engineering infrastructure** that plugs INTO existing agent frameworks (LangGraph, AutoGen, etc.), NOT as a competing agent framework.

**We own the hard problems:**
- Context growth → token limits blow up
- Reliability → non-deterministic behavior
- Cost → wasteful token usage
- Reproducibility → can't replay/debug runs
- Memory leaks → state bleeds between scopes

---

## Core Invariants (Must Own)

### 1. Context Object Model

| Component | Status | Action |
|-----------|--------|--------|
| `Context` (immutable) | ✅ Exists | Keep as-is |
| `ContextPatch` (provenance) | ❌ Missing | **ADD** |
| `PatchLog` (append-only) | ❌ Missing | **ADD** |
| `ContextCompiler` | ✅ Exists | Enhance to emit patches |
| `TokenBudget` | ✅ Exists | Keep as-is |

### 2. Execution Contracts

| Component | Status | Action |
|-----------|--------|--------|
| `Result[T]` | ✅ Exists | Keep as-is |
| `Tool` base | ✅ Exists | Enhance to record calls |
| Cancellation semantics | ❌ Missing | **ADD** |
| Timeout semantics | ⚠️ Partial | **ENHANCE** |

### 3. Memory Boundaries

| Component | Status | Action |
|-----------|--------|--------|
| `MemoryStore` | ✅ Exists | Keep as-is |
| `MemoryScope` | ✅ Exists | Keep as-is |
| `MemoryItem` | ✅ Exists | Keep as-is |
| TTL enforcement | ⚠️ Partial | **ENHANCE** |
| Redaction hooks | ❌ Missing | **ADD** |
| Serialization hooks | ❌ Missing | **ADD** |

### 4. Tracing/Events Contract

| Component | Status | Action |
|-----------|--------|--------|
| `EventBus` | ✅ Exists | Keep as-is |
| `Event` | ✅ Exists | Keep as-is |
| Context change events | ❌ Missing | **ADD** (emit on patch) |
| Tool invocation events | ⚠️ Partial | **ENHANCE** |

### 5. Replayability Contract

| Component | Status | Action |
|-----------|--------|--------|
| `RunLogger` | ❌ Missing | **ADD** |
| Tool call recording | ❌ Missing | **ADD** |
| Patch recording | ❌ Missing | **ADD** (via PatchLog) |
| Replay executor | ❌ Missing | **ADD** |

---

## Implementation Phases

### Phase 1: Context Patch System (Critical Differentiator)

**Files to create:**
- `src/cemaf/context/patch.py` - ContextPatch, PatchOperation, PatchSource, PatchLog

**Key types:**

```python
@dataclass(frozen=True)
class ContextPatch:
    path: str                    # "user.preferences.theme"
    operation: PatchOperation    # SET, DELETE, MERGE, APPEND
    value: Any

    # Provenance
    source: PatchSource          # TOOL, AGENT, LLM, SYSTEM, USER
    source_id: str               # "web_search", "research_agent"
    timestamp: datetime
    reason: str                  # Human-readable
    correlation_id: str | None   # For tracing

@dataclass(frozen=True)
class PatchLog:
    patches: tuple[ContextPatch, ...]

    def append(self, patch) -> PatchLog: ...
    def replay(self, initial: Context) -> Context: ...
    def filter_by_source(self, source) -> PatchLog: ...
```

**Enhance Context:**
```python
class Context:
    # Existing...

    def apply(self, patch: ContextPatch) -> Context:
        """Apply patch and return new context."""

    def diff(self, other: Context) -> tuple[ContextPatch, ...]:
        """Generate patches to transform self into other."""
```

### Phase 2: Run Logger & Recording

**Files to create:**
- `src/cemaf/observability/run_logger.py` - RunLogger protocol + implementation

**Key types:**

```python
@dataclass(frozen=True)
class ToolCall:
    tool_id: str
    input: JSON
    output: JSON
    duration_ms: float
    timestamp: datetime
    correlation_id: str

@dataclass(frozen=True)
class RunRecord:
    run_id: str
    initial_context: Context
    patches: PatchLog
    tool_calls: tuple[ToolCall, ...]
    final_context: Context

class RunLogger(Protocol):
    def record_tool_call(self, call: ToolCall) -> None: ...
    def record_patch(self, patch: ContextPatch) -> None: ...
    def get_record(self) -> RunRecord: ...
```

### Phase 3: Replay System

**Files to create:**
- `src/cemaf/replay/replayer.py` - Deterministic replay executor

**Key capability:**
```python
class Replayer:
    def __init__(self, record: RunRecord, mock_tools: dict[str, JSON]): ...

    async def replay(self) -> Context:
        """
        Replay run with mocked tool outputs.
        Given same patches + same tool outputs = same final context.
        """
```

### Phase 4: Cancellation & Timeout

**Files to modify:**
- `src/cemaf/core/execution.py` - Add ExecutionContext with cancellation

**Key types:**
```python
@dataclass
class ExecutionContext:
    cancellation_token: CancellationToken
    timeout_ms: int | None
    deadline: datetime | None

class CancellationToken:
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    def raise_if_cancelled(self) -> None: ...
```

### Phase 5: Memory Enhancements

**Files to modify:**
- `src/cemaf/memory/base.py` - Add hooks

**Key additions:**
```python
class MemoryStore(ABC):
    # Existing...

    # New hooks
    def set_redaction_hook(self, hook: Callable[[MemoryItem], MemoryItem]) -> None: ...
    def set_serialization_hook(self, hook: Callable[[MemoryItem], JSON]) -> None: ...

class MemoryItem:
    # Existing...

    ttl: timedelta | None = None  # Add TTL
    expires_at: datetime | None = None
```

### Phase 6: DAG Executor Integration

**Files to modify:**
- `src/cemaf/orchestration/executor.py` - Emit patches

**Key changes:**
```python
class DAGExecutor:
    def __init__(
        self,
        node_executor: NodeExecutor,
        run_logger: RunLogger | None = None,  # NEW
        event_bus: EventBus | None = None,    # NEW
    ): ...

    async def run(self, dag, context) -> ExecutionResult:
        # On each node completion:
        # 1. Create ContextPatch with provenance
        # 2. Record to run_logger
        # 3. Emit event
```

### Phase 7: Tool Integration

**Files to modify:**
- `src/cemaf/tools/base.py` - Add recording

**Key changes:**
```python
class Tool(ABC):
    # Existing...

    async def execute_with_recording(
        self,
        run_logger: RunLogger,
        correlation_id: str,
        **kwargs,
    ) -> ToolResult:
        """Execute and record to run logger."""
```

---

## New Event Types

Add to `src/cemaf/events/protocols.py`:

```python
class EventType(str, Enum):
    # Existing...

    # Context events (NEW)
    CONTEXT_PATCH_APPLIED = "context.patch.applied"
    CONTEXT_COMPILED = "context.compiled"
    CONTEXT_BUDGET_EXCEEDED = "context.budget.exceeded"

    # Tool events (NEW)
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"

    # Replay events (NEW)
    REPLAY_STARTED = "replay.started"
    REPLAY_COMPLETED = "replay.completed"
```

---

## File Structure (After)

```
src/cemaf/
├── context/
│   ├── __init__.py
│   ├── context.py          # Context (existing)
│   ├── patch.py            # ContextPatch, PatchLog (NEW)
│   ├── compiler.py         # ContextCompiler (existing)
│   ├── advanced_compiler.py
│   └── budget.py           # TokenBudget (existing)
├── core/
│   ├── result.py           # Result[T] (existing)
│   ├── execution.py        # ExecutionContext, CancellationToken (NEW)
│   └── ...
├── observability/
│   ├── run_logger.py       # RunLogger, ToolCall, RunRecord (NEW)
│   └── ...
├── replay/                 # NEW MODULE
│   ├── __init__.py
│   └── replayer.py         # Replayer
└── ...
```

---

## Integration Mode Support

### Mode A: CEMAF-in-the-middle
CEMAF owns execution, external frameworks are "engines".

```python
# CEMAF orchestrates, LangGraph executes nodes
executor = DAGExecutor(
    node_executor=LangGraphNodeExecutor(langgraph_app),
    run_logger=InMemoryRunLogger(),
)
result = await executor.run(dag, context)
```

### Mode B: CEMAF-as-library
External frameworks orchestrate, CEMAF provides infrastructure.

```python
# LangGraph orchestrates, CEMAF provides context layer
@langgraph_node
def my_node(state):
    ctx = cemaf.Context.from_dict(state)
    patch = ContextPatch.from_tool("search", "results", search_results)
    ctx = ctx.apply(patch)
    run_logger.record_patch(patch)
    compiled = compiler.compile(ctx, budget)
    return compiled.to_dict()
```

---

## Testing Strategy

1. **Unit tests** for each new type (ContextPatch, PatchLog, etc.)
2. **Integration tests** for DAG executor with patching
3. **Replay tests** - Record a run, replay with mocks, assert same result
4. **Stress tests** - Context explosion scenarios

---

## Documentation Updates

1. **docs/context.md** - Add ContextPatch, PatchLog sections
2. **docs/replay.md** - New doc for replayability
3. **docs/integration.md** - New doc for Mode A/B integration
4. **README.md** - Update positioning to emphasize context engineering

---

## Success Metrics

- [ ] Can record any run as patches + tool calls
- [ ] Can replay any recorded run deterministically
- [ ] Context changes are traceable to their source
- [ ] Token budget is enforced at compile time
- [ ] Memory scopes prevent cross-contamination
- [ ] Cancellation/timeout work across all executors

---

## Questions for Review

1. Should `ContextPatch.apply()` be on Context or a separate function?
2. Should `RunLogger` be synchronous or async?
3. Should replay be a separate module or part of orchestration?
4. How should TTL be enforced - lazy (on read) or eager (background)?
