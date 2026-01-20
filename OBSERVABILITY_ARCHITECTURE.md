# CEMAF Observability Architecture

## Executive Summary

CEMAF's observability system is **fully coherent** across checkpoint/replay, tracing, health monitoring, performance, cost tracking, and reproducibility. The **correlation_id** (derived from run_id) is the golden thread linking all systems.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│         Application Layer (DAG Execution)                    │
│  - Orchestrates agent workflows                             │
│  - Manages state transitions via Context patches            │
│  - Emits correlation IDs for distributed tracing            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│      Observability Layer (Logging + Monitoring)              │
│  - RunLogger: Records execution history                      │
│  - HealthMonitor: System health checks (NEW)                 │
│  - Logger: Debug/info/warn/error with lazy evaluation (NEW) │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│    State Management Layer (Context + Patches)                │
│  - Context: Immutable state container                        │
│  - ContextPatch: Provenance-tracked state changes            │
│  - PatchLog: Deterministic replay capability                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│      Persistence Layer (Checkpointing + Replay)              │
│  - Checkpointer: Periodic state snapshots                    │
│  - Replayer: Deterministic execution reconstruction          │
│  - Storage: Pluggable persistence backends                   │
└─────────────────────────────────────────────────────────────┘
```

## 1. Correlation ID: The Golden Thread

**Every artifact links to execution via `correlation_id = run_id`:**

```python
RunID: "run_abc123"
  │
  ├─→ DAGCheckpoint
  │    ├─ run_id: "run_abc123"
  │    └─ Contains: Context snapshot, completed/pending nodes
  │
  ├─→ RunRecord
  │    ├─ run_id: "run_abc123"
  │    ├─ patches[] (each has correlation_id)
  │    ├─ tool_calls[] (each has correlation_id)
  │    └─ llm_calls[] (each has correlation_id + token counts)
  │
  ├─→ ContextPatch
  │    ├─ correlation_id: "run_abc123"
  │    ├─ source: TOOL/AGENT/LLM/SYSTEM/USER
  │    ├─ source_id: "web_search_tool"
  │    ├─ reason: "Search results for 'CEMAF'"
  │    └─ timestamp: 2025-01-19T10:30:45Z
  │
  ├─→ ToolCall
  │    ├─ correlation_id: "run_abc123"
  │    ├─ tool_id: "web_search"
  │    ├─ duration_ms: 523.4
  │    └─ timestamp
  │
  └─→ LLMCall
       ├─ correlation_id: "run_abc123"
       ├─ model: "gpt-4"
       ├─ input_tokens: 1542  ← COST TRACKING
       ├─ output_tokens: 487  ← COST TRACKING
       └─ duration_ms: 2134.5
```

## 2. Checkpoint ↔ Replay ↔ Traceability

### 2.1 Checkpoint System

**What gets saved:**
```python
@dataclass(frozen=True)
class DAGCheckpoint:
    run_id: RunID
    dag_name: str
    status: RunStatus                    # RUNNING/FAILED/COMPLETED
    completed_nodes: tuple[NodeID, ...]  # Already executed
    pending_nodes: tuple[NodeID, ...]    # Remaining
    context: Context                     # EXACT STATE
    error: str | None
    failed_node: NodeID | None
    checkpoint_time: datetime
```

**When saved:**
- Every N nodes (configurable interval)
- On node failure
- On completion

**Resume capability:**
```python
# Load checkpoint
checkpoint = await checkpointer.load(run_id)

# Resume from exact state
result = await executor.resume(
    run_id=checkpoint.run_id,
    dag=dag,
    # Uses checkpoint.context as starting state
    # Only executes checkpoint.pending_nodes
)
```

### 2.2 Replay System

**Three modes:**

| Mode | Description | Use Case |
|------|-------------|----------|
| `PATCH_ONLY` | Apply patches to initial context | Fastest, deterministic reconstruction |
| `MOCK_TOOLS` | Replay with mocked tool outputs | Testing, validation |
| `LIVE_TOOLS` | Re-execute tools with real calls | Debugging, production verification |

**Replay workflow:**
```python
# From RunRecord
record = run_logger.get_run(run_id)

# Replay deterministically
replayer = Replayer(record)
final_context = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

# Verify determinism
is_identical = (final_context == record.final_context)
```

### 2.3 Traceability via Patches

**Every state change is tracked:**
```python
patch = ContextPatch(
    path="search.results",
    operation=PatchOperation.SET,
    value=["result1", "result2"],

    # PROVENANCE (WHO)
    source=PatchSource.TOOL,
    source_id="web_search_tool",

    # TRACEABILITY (WHEN/WHY/WHERE)
    timestamp=utc_now(),
    reason="Search results for query 'CEMAF'",
    correlation_id=run_id,  # Links to execution

    id="patch_xyz789",  # Unique ID
)
```

**Filtering capabilities:**
```python
patch_log = PatchLog(record.patches)

# All patches from specific tool
tool_patches = patch_log.filter_by_source_id("web_search_tool")

# All patches in time range
recent = patch_log.filter_by_time_range(start, end)

# All patches affecting specific path
search_changes = patch_log.filter_by_path_prefix("search")

# All patches from a specific run
run_patches = patch_log.filter_by_correlation_id(run_id)
```

## 3. Health Monitoring (NEW)

### 3.1 HealthMonitor Integration

```python
from cemaf.observability import get_health_monitor

# Register checks
health = get_health_monitor()

def check_llm_connection():
    try:
        # Test LLM provider
        return HealthCheckResult("llm", HealthStatus.HEALTHY)
    except Exception as e:
        return HealthCheckResult(
            "llm",
            HealthStatus.UNHEALTHY,
            message=str(e)
        )

health.register_check("llm", check_llm_connection, critical=True)

# During execution
result = await health.check_all()
if result.status == HealthStatus.UNHEALTHY:
    # Log and alert
    logger.error("System unhealthy: %s", result.message)
```

### 3.2 Health Check States

| Status | Meaning | Action |
|--------|---------|--------|
| HEALTHY | All systems operational | Continue |
| DEGRADED | Non-critical failures | Log warning, continue |
| UNHEALTHY | Critical failures | Alert, possibly abort |

## 4. Performance Tracking

### 4.1 Timing Capture

**All operations timed:**
```python
# Tool calls
ToolCall(
    tool_id="web_search",
    duration_ms=523.4,  # Execution time
    ...
)

# LLM calls
LLMCall(
    model="gpt-4",
    duration_ms=2134.5,  # LLM response time
    ...
)
```

### 4.2 Performance Analysis

```python
# From RunRecord
total_execution_time = (
    record.completed_at - record.started_at
).total_seconds()

# Tool performance
tool_stats = {
    tool_id: {
        "count": len(calls),
        "total_ms": sum(c.duration_ms for c in calls),
        "avg_ms": mean(c.duration_ms for c in calls),
    }
    for tool_id, calls in group_by(record.tool_calls, 'tool_id')
}

# LLM performance
llm_stats = {
    "total_calls": len(record.llm_calls),
    "total_duration_ms": sum(c.duration_ms for c in record.llm_calls),
    "avg_duration_ms": mean(c.duration_ms for c in record.llm_calls),
}
```

## 5. Cost Tracking & Budget Enforcement

### 5.1 Token Budget System

**Budget definition:**
```python
from cemaf.context.budget import TokenBudget

# Model-specific budget
budget = TokenBudget.for_model("gpt-4")  # 8,192 tokens
budget = TokenBudget.for_model("claude-3-sonnet")  # 200,000 tokens

# Custom budget with allocations
budget = (
    TokenBudget(max_tokens=10_000, reserved_for_output=2_000)
    .with_allocation("system", max_tokens=1_000, priority=10)
    .with_allocation("memories", max_tokens=4_000, priority=5)
    .with_allocation("artifacts", max_tokens=3_000, priority=1)
)

# Check available tokens
available = budget.available_tokens  # max_tokens - reserved_for_output
```

### 5.2 Cost Tracking via LLMCall

**Capture at execution time:**
```python
# LLM provider returns token usage
response = await llm_client.complete(messages)

# Record with token counts
llm_call = LLMCall(
    model="gpt-4",
    input_messages=messages,
    output=response.content,
    input_tokens=response.usage.input_tokens,    # FROM PROVIDER
    output_tokens=response.usage.output_tokens,  # FROM PROVIDER
    duration_ms=elapsed_ms,
    correlation_id=run_id,
)

run_logger.record_llm_call(llm_call)
```

### 5.3 Cost Analysis

```python
# From RunRecord
def calculate_cost(record: RunRecord) -> dict:
    """Calculate execution cost from token usage."""

    # Pricing (example)
    pricing = {
        "gpt-4": {"input": 0.03 / 1000, "output": 0.06 / 1000},
        "gpt-4-turbo": {"input": 0.01 / 1000, "output": 0.03 / 1000},
        "claude-3-sonnet": {"input": 0.003 / 1000, "output": 0.015 / 1000},
    }

    total_cost = 0.0
    for call in record.llm_calls:
        rates = pricing.get(call.model, {"input": 0, "output": 0})
        cost = (
            call.input_tokens * rates["input"] +
            call.output_tokens * rates["output"]
        )
        total_cost += cost

    return {
        "total_cost": total_cost,
        "total_tokens": sum(
            c.input_tokens + c.output_tokens
            for c in record.llm_calls
        ),
        "by_model": {
            model: sum(
                c.input_tokens + c.output_tokens
                for c in calls
            )
            for model, calls in group_by(record.llm_calls, 'model')
        },
    }
```

## 6. Reproducibility Guarantees

### 6.1 Deterministic Replay

**Patches enable exact reproduction:**
```python
# Original execution
context₀ + patch₁ → context₁
context₁ + patch₂ → context₂
context₂ + patch₃ → context₃

# Replay (ALWAYS identical)
context₀ + patch₁ → context₁'  (context₁' == context₁)
context₁' + patch₂ → context₂' (context₂' == context₂)
context₂' + patch₃ → context₃' (context₃' == context₃)
```

**Verification:**
```python
# Replay execution
replayed_context = await replayer.replay(
    mode=ReplayMode.PATCH_ONLY,
    initial_context=record.initial_context,
)

# Verify identical
assert replayed_context == record.final_context

# Or detect divergences
differences = replayed_context.diff(record.final_context)
if differences:
    for diff in differences:
        logger.error(
            "Divergence at %s: expected %s, got %s",
            diff.path,
            diff.expected,
            diff.actual,
        )
```

### 6.2 Mock Replay for Testing

```python
# Define mocks
mock_tools = {
    "web_search": lambda input: {"results": ["mock1", "mock2"]},
    "llm_call": lambda input: "Mock LLM response",
}

# Replay with mocks
replayed = await replayer.replay(
    mode=ReplayMode.MOCK_TOOLS,
    mock_tools=mock_tools,
)

# Verify behavior
assert "mock1" in replayed.context.get("search.results")
```

## 7. Logging Infrastructure (NEW)

### 7.1 Lazy Logging with % Formatting

**Why lazy evaluation:**
```python
# BAD (f-string): Always evaluated, even if debug disabled
logger.debug(f"Processing {len(items)} items: {items}")
# ^ Expensive string formatting happens EVERY TIME

# GOOD (% formatting): Only evaluated if debug enabled
logger.debug("Processing %d items: %s", len(items), items)
# ^ Only formats if logger.isEnabledFor(logging.DEBUG)
```

### 7.2 Structured Context

```python
from cemaf.observability import get_logger

logger = get_logger("dag.executor")

# Add structured context
logger = logger.with_context(run_id=run_id, dag_name=dag.name)

# All logs include context
logger.info("Starting execution")
# Output: "Starting execution | run_id=run_abc123 | dag_name=research_workflow"

logger.debug("Executing node %s", node.id, node_type=node.type.value)
# Output (if debug enabled): "Executing node research_node | run_id=run_abc123 | node_type=TOOL"
```

### 7.3 Configuration

```python
from cemaf.observability import configure_logging

# Set log level
configure_logging(level="DEBUG")

# Or via environment variable
# export CEMAF_LOG_LEVEL=DEBUG

# Custom logger implementation
configure_logging(logger=MyStructuredLogger())
```

## 8. Data Flow: Complete Picture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INITIATES RUN                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  1. INITIALIZATION                                           │
│  - Generate run_id                                           │
│  - Create initial Context                                    │
│  - Configure budget (TokenBudget.for_model)                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  2. LOGGING START                                            │
│  - run_logger.start_run(run_id, dag_name, initial_context)  │
│  - Creates RunRecord                                         │
│  - logger.info("Starting execution", run_id=run_id)          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  3. CHECKPOINT (Initial)                                     │
│  - Save DAGCheckpoint(status=RUNNING, pending_nodes=all)     │
│  - logger.debug("Checkpoint saved", checkpoint_id=...)       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  4. NODE EXECUTION (Loop)                                    │
│  For each node:                                              │
│    ├─ Check health: health.check_all()                       │
│    ├─ Execute node → NodeResult                              │
│    ├─ Record timing: duration_ms                             │
│    ├─ If tool used:                                          │
│    │   └─ run_logger.record_tool_call(ToolCall(...))         │
│    ├─ If LLM used:                                           │
│    │   ├─ Check budget: budget.available_tokens              │
│    │   ├─ Call LLM                                           │
│    │   └─ run_logger.record_llm_call(LLMCall(              │
│    │        input_tokens=..., output_tokens=...))            │
│    ├─ Create ContextPatch:                                   │
│    │   └─ correlation_id=run_id, source_id=node.id          │
│    ├─ run_logger.record_patch(patch)                         │
│    ├─ context = context.apply(patch)                         │
│    ├─ logger.debug("Node executed", node_id=...)             │
│    └─ Save checkpoint (if interval reached)                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  5. COMPLETION                                               │
│  - run_logger.end_run(final_context, success, error)         │
│  - Save final checkpoint (status=COMPLETED)                  │
│  - logger.info("Execution completed", success=True)          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  6. ANALYSIS & OBSERVABILITY                                 │
│  - Cost: calculate_cost(run_record)                          │
│  - Performance: analyze_timing(run_record)                   │
│  - Replay: replayer.replay(mode=PATCH_ONLY)                  │
│  - Health: health.check_all()                                │
│  - Traceability: filter patches by correlation_id            │
└─────────────────────────────────────────────────────────────┘
```

## 9. Coherence Checklist

✅ **Checkpoint ↔ Replay**
- Checkpoints save exact Context state
- Replayer reconstructs Context from patches
- Resume uses checkpoint Context as starting point

✅ **Traceability ↔ Logging**
- correlation_id links all artifacts
- Patches record full provenance (who/what/when/why)
- Logger adds structured context (run_id, node_id, etc.)

✅ **Health ↔ Execution**
- HealthMonitor checks system state before execution
- Can abort on UNHEALTHY status
- Integrates with logger for warnings/errors

✅ **Performance ↔ Cost**
- ToolCall records duration_ms
- LLMCall records duration_ms + token counts
- Both link to run_id for aggregation

✅ **Cost ↔ Budget**
- TokenBudget defines limits before execution
- LLMCall captures actual usage during execution
- Can compare budget.available_tokens vs actual usage

✅ **Reproducibility ↔ Patches**
- Patches are deterministic transformations
- Replay on same initial_context = identical final_context
- Mock replay enables testing without side effects

## 10. Key Strengths

### Full Provenance
Every state change records:
- **WHO**: source (TOOL/AGENT/LLM/SYSTEM/USER), source_id
- **WHAT**: path, operation, value
- **WHEN**: timestamp
- **WHY**: reason (human-readable)
- **WHERE**: correlation_id (links to run)

### Deterministic Replay
- Patches enable exact reproduction
- Verification detects non-determinism
- Testing with mocks avoids side effects

### Cost Transparency
- Token counts from LLM providers
- Aggregation by model, time range
- Budget vs actual comparison

### Resilient Execution
- Checkpoints at configurable intervals
- Resume from exact failure point
- No redundant re-execution

### Observable System
- Structured logging with lazy evaluation
- Health monitoring with HEALTHY/DEGRADED/UNHEALTHY
- Performance tracking (duration_ms)
- Correlation via run_id

## 11. Usage Example

```python
from cemaf.observability import get_logger, get_health_monitor, configure_logging
from cemaf.orchestration import DAGExecutor, CheckpointingDAGExecutor
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.context import Context
from cemaf.context.budget import TokenBudget

# 1. Configure observability
configure_logging(level="INFO")
logger = get_logger("my_app")
health = get_health_monitor()

# 2. Register health checks
def check_llm():
    # Test LLM connectivity
    return HealthCheckResult("llm", HealthStatus.HEALTHY)

health.register_check("llm", check_llm, critical=True)

# 3. Create executor with logging + checkpointing
run_logger = InMemoryRunLogger()
base_executor = DAGExecutor(
    node_executor=my_node_executor,
    run_logger=run_logger,  # Records everything
)
executor = CheckpointingDAGExecutor(
    base_executor=base_executor,
    checkpointer=my_checkpointer,  # Saves state
    checkpoint_interval=1,  # Every node
)

# 4. Define budget
budget = TokenBudget.for_model("gpt-4")

# 5. Execute
context = Context(data={"query": "research CEMAF"})
result = await executor.run(
    dag=my_dag,
    initial_context=context,
    run_id="run_123",
)

# 6. Analyze
record = run_logger.get_run("run_123")

# Cost
cost = calculate_cost(record)
logger.info("Execution cost: $%.4f", cost["total_cost"])

# Performance
duration_s = (record.completed_at - record.started_at).total_seconds()
logger.info("Execution time: %.2fs", duration_s)

# Health
health_result = await health.check_all()
if health_result.status != HealthStatus.HEALTHY:
    logger.warning("System health: %s", health_result.message)

# 7. Replay (for debugging)
from cemaf.replay import Replayer

replayer = Replayer(record)
replayed = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

# Verify determinism
assert replayed == record.final_context
```

## Conclusion

CEMAF's observability architecture is **highly coherent** with:
- ✅ Full traceability via correlation_id
- ✅ Deterministic replay via patches
- ✅ Cost tracking via LLMCall token counts
- ✅ Performance monitoring via duration_ms
- ✅ Health checks via HealthMonitor
- ✅ Lazy logging for efficiency
- ✅ Checkpoint/resume for resilience

All systems integrate seamlessly through shared data structures and the correlation_id linking mechanism.
