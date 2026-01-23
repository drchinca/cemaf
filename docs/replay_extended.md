# Replay Module - Extended Documentation

## Overview

The replay module enables deterministic re-execution of agent runs, allowing exact reproduction of previous execution paths with different replay strategies.

**What it does**: Given a RunRecord containing all tool calls, patches, and context changes, replays the run in multiple modes: applying patches only, re-executing with mocked tool outputs, or validating against live tool implementations. This enables debugging, testing behavior changes, validating output consistency, and understanding divergences from original runs.

**Key use cases**:
- Debugging agent behavior by replaying exact execution path
- Testing agent changes without re-running expensive tools
- Validating consistency between deterministic and live execution
- Building regression test suites from production runs
- Understanding where and why a run diverged from expected behavior

**When to use vs. alternatives**: Use replay when you need exact determinism or want to understand specific historical executions. Use it for testing changes to orchestration logic. Don't use for testing new tool implementations (use integration tests) or simulating behavior without history (use mocking directly).

## Core Concepts

### Replay Modes

**PATCH_ONLY**: The fastest and most deterministic mode. Simply applies recorded patches to an initial context in sequence. Patches represent all state changes recorded during the original run. This mode is perfect for testing orchestration changes, validating patch application logic, and regression testing.

**MOCK_TOOLS**: Re-executes the same tool calls but injects the original outputs. The orchestration logic runs again, allowing you to validate that the same inputs produce the same outputs. Useful when you've modified tool calling logic but want to verify it still works with known outputs.

**LIVE_TOOLS**: Re-executes with actual tool implementations, connecting to real external services. This validates that the agent can work with current real-world data. Divergences from the original run reveal what's changed in external systems (API responses, availability, etc.).

### Determinism Guarantees

PATCH_ONLY guarantees determinism because it doesn't execute any code. MOCK_TOOLS is deterministic if your tool implementations are deterministic. LIVE_TOOLS cannot guarantee determinism because external systems change.

```python
# PATCH_ONLY is always deterministic
result1 = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
result2 = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
assert result1.final_context == result2.final_context  # Always true

# MOCK_TOOLS is deterministic if tools are
result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)
# With same mocked outputs, always same result

# LIVE_TOOLS may diverge
result1 = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
result2 = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
# result1.final_context may != result2.final_context
```

### Divergence Detection

The replay system compares final contexts and records divergences. A divergence is any observable difference from the original run:

- Different context values (source, summary, decisions)
- Different tool outputs
- Different structured outputs
- Different completion status

This enables understanding what changed when you modify agent behavior.

### Recording and Playback Architecture

The RunRecord captures:
- Tool calls with exact input arguments
- Tool outputs (or error messages)
- Context patches applied at each step
- Final context state
- Execution metadata

From this record, any replay mode can reconstruct the execution.

## Usage Examples

### Basic Deterministic Replay

```python
from cemaf.replay.replayer import Replayer, ReplayMode
from cemaf.observability.run_logger import RunLogger

# Retrieve original run record
logger = RunLogger()
original_record = await logger.get_record(run_id)

# Replay with patches only (deterministic)
replayer = Replayer(original_record)
result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

assert result.success
assert result.mode == ReplayMode.PATCH_ONLY
print(f"Applied {result.patches_applied} patches")
print(f"Duration: {result.duration_ms}ms")

# Final context matches original
assert result.final_context == original_record.final_context
```

### Testing Orchestration Changes

```python
# Original run with old orchestration
original_record = await logger.get_record("run_old")

# Modify agent logic (new prompt, different tool selection, etc.)
# Then replay to validate behavior change
replayer = Replayer(original_record)
result_patch = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
result_mock = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

# Compare divergences to understand what changed
if result_mock.divergences:
    print(f"Detected {len(result_mock.divergences)} divergences:")
    for div in result_mock.divergences:
        print(f"  - {div}")

# Validate that changes are intentional
assert result_mock.success
print("Orchestration change validated against historical data")
```

### Regression Testing

```python
# Build test suite from production runs
production_runs = await logger.list_records(
    status=RunStatus.COMPLETED,
    limit=100
)

regression_tests = []
for record in production_runs:
    test = {
        "run_id": record.run_id,
        "original_context": record.final_context,
        "record": record
    }
    regression_tests.append(test)

# When you deploy new agent version, replay all
failed_tests = []
for test in regression_tests:
    replayer = Replayer(test["record"])
    result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

    if not result.success or result.divergences:
        failed_tests.append({
            "run_id": test["run_id"],
            "result": result
        })

# Report regressions
if failed_tests:
    print(f"WARNING: {len(failed_tests)} regressions detected")
    for test in failed_tests[:5]:  # Show first 5
        print(f"  - {test['run_id']}: {test['result'].error}")
```

### Validating Against Real Tools

```python
# Validate that live tools still work
record = await logger.get_record(run_id)
replayer = Replayer(record)

# Replay with real tools
result = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)

if not result.success:
    print(f"Tool execution failed: {result.error}")
    # Tools may be down or changed

if result.divergences:
    print(f"Tool outputs diverged ({len(result.divergences)} differences)")
    print("External data has changed since original run")
    # This is expected and informational

print(f"Replayed {result.tools_replayed} tools")
```

### Comparing Multiple Replay Modes

```python
record = await logger.get_record(run_id)
replayer = Replayer(record)

# Compare all modes
results = {}
for mode in [ReplayMode.PATCH_ONLY, ReplayMode.MOCK_TOOLS, ReplayMode.LIVE_TOOLS]:
    try:
        result = await replayer.replay(mode=mode)
        results[mode.value] = {
            "success": result.success,
            "duration_ms": result.duration_ms,
            "divergences": len(result.divergences),
            "error": result.error
        }
    except Exception as e:
        results[mode.value] = {"error": str(e)}

# Analysis
print(f"Patch-only: {results['patch_only']['duration_ms']:.1f}ms (deterministic)")
print(f"Mock tools: {results['mock_tools']['duration_ms']:.1f}ms (with execution)")
print(f"Live tools: {results['live_tools']['duration_ms']:.1f}ms (with real calls)")

# PATCH_ONLY should always work
assert results['patch_only']['success']
```

### Debugging Tool Outputs

```python
# When a run failed or produced unexpected output
record = await logger.get_record("run_with_issue")

# Inspect original tool calls
for tool_call in record.tool_calls:
    print(f"Tool: {tool_call.name}")
    print(f"  Input: {tool_call.input}")
    print(f"  Output: {tool_call.output}")
    if tool_call.error:
        print(f"  Error: {tool_call.error}")

# Replay with those exact outputs mocked
replayer = Replayer(record)
result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

# If it succeeds now, issue was in orchestration, not tools
if result.success and not result.divergences:
    print("Confirmed: Tools worked, orchestration processed outputs correctly")

# Check what final context looks like
print(f"Final source count: {len(result.final_context.sources)}")
print(f"Final decisions: {result.final_context.decisions}")
```

### Common Mistake: Assuming Determinism

```python
# ❌ WRONG - Assuming LIVE_TOOLS is deterministic
result1 = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
result2 = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
assert result1.final_context == result2.final_context  # May fail!

# ✅ CORRECT - Only assume PATCH_ONLY is deterministic
result1 = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
result2 = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
assert result1.final_context == result2.final_context  # Always true

# ✅ CORRECT - Use LIVE_TOOLS for validation, not reproduction
result = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
if result.divergences:
    print("Note: External data has changed since original run")
```

## Integration

### With Observability Module

Replay uses RunRecord from the observability module:

```python
from cemaf.observability.run_logger import RunLogger
from cemaf.replay.replayer import Replayer

logger = RunLogger()
record = await logger.get_record(run_id)

# Record contains all data needed for replay
replayer = Replayer(record)
result = await replayer.replay()
```

### With Context Module

Replay reconstructs Context objects from patches:

```python
from cemaf.context.context import Context
from cemaf.replay.replayer import Replayer

replayer = Replayer(record)
result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

# result.final_context is a fully reconstructed Context
# with all sources, decisions, summaries, etc.
print(result.final_context.sources)
print(result.final_context.decisions)
```

### With Testing Frameworks

Use replay in test suites:

```python
import pytest
from cemaf.replay.replayer import Replayer
from cemaf.observability.run_logger import RunLogger

@pytest.fixture
async def regression_data(logger: RunLogger):
    """Load production runs for regression testing."""
    records = await logger.list_records(limit=50)
    return records

@pytest.mark.asyncio
async def test_replay_regression(regression_data):
    """Ensure new code still replays old runs correctly."""
    for record in regression_data:
        replayer = Replayer(record)
        result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)
        assert result.success, f"Regression in {record.run_id}"
        assert len(result.divergences) == 0, f"Divergences in {record.run_id}"
```

### With Persistence Module

Store replay results for analysis:

```python
from cemaf.persistence.entities import Run, RunStatus

# After replay
result = await replayer.replay()

# Store result
run_record = Run(
    project_id=project_id,
    pipeline="replay_validation",
    inputs={"original_run_id": original_run_id},
    outputs={
        "replay_success": result.success,
        "divergences": len(result.divergences),
        "duration_ms": result.duration_ms,
        "divergence_details": list(result.divergences)
    },
    status=RunStatus.COMPLETED if result.success else RunStatus.FAILED
)
await run_store.create(run_record)
```

## API Reference

### ReplayMode Enum

```python
class ReplayMode(str, Enum):
    PATCH_ONLY = "patch_only"      # Apply patches only (fastest, deterministic)
    MOCK_TOOLS = "mock_tools"      # Re-execute with mocked outputs
    LIVE_TOOLS = "live_tools"      # Re-execute with real tools
```

### ReplayResult Dataclass

```python
@dataclass(frozen=True)
class ReplayResult:
    success: bool                           # Whether replay succeeded
    final_context: Context                  # Reconstructed context
    mode: ReplayMode                        # Which mode was used
    duration_ms: float = 0.0               # Execution time
    patches_applied: int = 0               # How many patches applied
    tools_replayed: int = 0                # How many tools re-executed
    divergences: tuple[str, ...] = ()      # Differences from original
    error: str | None = None               # Error message if failed

    @classmethod
    def ok(
        cls,
        final_context: Context,
        mode: ReplayMode,
        duration_ms: float = 0.0,
        patches_applied: int = 0,
        tools_replayed: int = 0,
        divergences: tuple[str, ...] = ()
    ) -> ReplayResult

    @classmethod
    def fail(
        cls,
        error: str,
        final_context: Context,
        mode: ReplayMode
    ) -> ReplayResult
```

### Replayer Class

```python
class Replayer:
    def __init__(
        self,
        record: RunRecord,
        mocked_outputs: dict[str, Any] | None = None
    ):
        """Initialize replayer with a run record.

        Args:
            record: The RunRecord to replay
            mocked_outputs: Tool outputs to inject for MOCK_TOOLS mode
        """

    async def replay(
        self,
        mode: ReplayMode = ReplayMode.PATCH_ONLY
    ) -> ReplayResult:
        """Execute the replay.

        Args:
            mode: Which replay mode to use

        Returns:
            ReplayResult with final context and metadata
        """
```

## Best Practices

### Performance Tips

- **Use PATCH_ONLY for testing**: It's 10-100x faster since it doesn't execute code. Only use MOCK_TOOLS or LIVE_TOOLS when you actually need execution.
- **Batch replays**: When replaying multiple runs, use async/await to run them in parallel:
  ```python
  results = await asyncio.gather(
      replayer1.replay(),
      replayer2.replay(),
      replayer3.replay()
  )
  ```
- **Cache deterministic results**: PATCH_ONLY results are deterministic, so cache them
- **Lazy load records**: Load RunRecords on-demand rather than preloading all

### Common Pitfalls

**Ignoring divergences**: A successful replay with divergences means behavior changed. Investigate why. It's often intentional but should be understood.

**Expecting LIVE_TOOLS determinism**: External APIs change. LIVE_TOOLS replays will diverge. Use this to detect what changed, not to assert identical results.

**Not comparing modes**: Always compare PATCH_ONLY vs MOCK_TOOLS to understand where execution diverges from patches. This reveals bugs.

**Forgetting tool outputs**: MOCK_TOOLS requires you specify mock outputs. If you don't, it falls back to the original recorded outputs. This is usually what you want but be explicit about it.

**Replaying changed tools**: If you've changed tool implementations, MOCK_TOOLS will use new code with old inputs. Use LIVE_TOOLS to validate against current implementations.

### When NOT to Use

- **Single run debugging**: For a single failed run, read the logs directly. Replay is overkill.
- **Behavior simulation**: Don't use replay to simulate "what if" scenarios. Use mocking directly.
- **Performance testing**: Replay is for correctness, not benchmarking. Use dedicated tools for performance.
- **Load testing**: Don't replay hundreds of runs to stress-test systems. Use load testing tools.

### Regression Testing Strategy

```python
# Good: Test against diverse production examples
@pytest.fixture
async def production_samples():
    logger = RunLogger()
    # Sample from different dates, users, content types
    return await logger.list_records(
        status=RunStatus.COMPLETED,
        limit=100,
        random_sample=True
    )

# Bad: Testing only with synthetic data
@pytest.fixture
def synthetic_samples():
    return [create_mock_run_record() for _ in range(100)]
```

### Divergence Analysis

When you see divergences, systematically investigate:

```python
result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

if result.divergences:
    # 1. Check if intentional
    for div in result.divergences:
        print(f"Divergence: {div}")
        # Ask: Did I intentionally change this?

    # 2. If unintentional, run in PATCH_ONLY to isolate
    result_patch = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
    # If PATCH_ONLY succeeds, divergence is in tool execution

    # 3. Compare with LIVE_TOOLS to see what changed
    result_live = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
    # If LIVE_TOOLS has same divergences, external system changed
```

### Recording Complete Metadata

For replay to work well, record all necessary data:

```python
# ✅ GOOD - Complete input capture
tool_call = {
    "name": "search",
    "input": {"query": "...", "limit": 10},  # All parameters
    "output": {...},  # Full response
    "timestamp": utc_now()
}

# ❌ BAD - Partial capture
tool_call = {
    "name": "search",
    "output": {...}
    # No input - can't replay
}
```
