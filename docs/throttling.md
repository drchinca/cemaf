# Resource Guards & Throttling

Edge devices overheat. Memory fills up. CEMAF keeps running.

This module provides **resource-aware execution** for agents on constrained hardware.

## The Constraint Reality

| Device | RAM | CPU Thermal Limit | Storage |
|--------|-----|-------------------|---------|
| Raspberry Pi 4 | 4GB | 85°C | SD card |
| Jetson Nano | 4GB | 100°C | 16GB eMMC |
| Intel NUC | 8GB | 100°C | 128GB SSD |
| ESP32 | 520KB | N/A | 4MB |

When any resource exceeds safe limits, the agent must **pause, not crash**.

## Circuit Breaker for Resources

```python
from cemaf.throttling import ResourceCircuitBreaker

breaker = ResourceCircuitBreaker(
    thresholds={
        "cpu_percent": 90,      # Pause if CPU > 90%
        "memory_percent": 85,   # Pause if RAM > 85%
        "temperature_c": 80,    # Pause if temp > 80°C
        "disk_percent": 95,     # Pause if disk > 95%
    },
    cooldown_seconds=30,        # Wait before resuming
    check_interval_seconds=5,   # Poll frequency
)

# Wrap DAG execution
@breaker.guard
async def run_agent():
    result = await executor.run(dag, context)
    return result

# Or use as context manager
async with breaker.guarded():
    result = await executor.run(dag, context)
```

### Breaker States

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Resource Circuit Breaker States                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌──────────┐         Threshold         ┌──────────┐              │
│   │  CLOSED  │ ──────── Exceeded ───────▶│   OPEN   │              │
│   │ (Normal) │                           │ (Paused) │              │
│   └──────────┘                           └──────────┘              │
│        ▲                                       │                    │
│        │                                       │                    │
│        │         ┌───────────┐                 │                    │
│        └──────── │ HALF-OPEN │ ◀── Cooldown ───┘                   │
│     Resources    │  (Probe)  │     Expired                         │
│     Recovered    └───────────┘                                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Context Paging

When RAM is full, spill context to disk:

```python
from cemaf.throttling import ContextPager

pager = ContextPager(
    memory_limit_mb=256,        # Max context in RAM
    page_size_mb=16,            # Chunk size for paging
    storage_path="/tmp/cemaf_pages",
    compression="lz4",          # Fast compression
)

# Wrap context operations
paged_context = pager.wrap(context)

# Access works normally - paging is transparent
value = paged_context.get("large_document")

# Monitor paging activity
stats = pager.stats()
print(f"Pages in RAM: {stats.pages_in_memory}")
print(f"Pages on disk: {stats.pages_on_disk}")
print(f"Page hits: {stats.hit_rate:.1%}")
```

### How Paging Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Context Paging Strategy                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Context Data (2GB total)                                          │
│   ├── system_prompt ──────────▶ RAM (always resident)              │
│   ├── recent_messages ────────▶ RAM (hot)                          │
│   ├── tool_results ───────────▶ RAM (warm) ──┬──▶ Disk (cold)      │
│   ├── old_memory ─────────────▶ Disk (cold)  │                     │
│   └── document_chunks ────────▶ Disk (cold) ◀┘                     │
│                                                                     │
│   Page Eviction: LRU (Least Recently Used)                         │
│   Page-in: On access, async prefetch for sequential reads          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Pinned Pages

Critical context stays in memory:

```python
paged_context = pager.wrap(
    context,
    pin_keys=["system_prompt", "user_preferences"],  # Never page out
    prefetch_keys=["recent_messages"],               # Load on startup
)
```

## CPU Throttling

Limit LLM inference speed to prevent thermal throttling:

```python
from cemaf.throttling import CPUThrottler

throttler = CPUThrottler(
    target_cpu_percent=70,      # Stay under 70% CPU
    sample_window_seconds=5,     # Measure over 5s window
    throttle_strategy="delay",   # Add delays between operations
)

# Apply to LLM client
throttled_llm = throttler.wrap(llm_client)

# Inference is automatically paced
response = await throttled_llm.complete(messages)
```

### Thermal Management

```python
from cemaf.throttling import ThermalManager

thermal = ThermalManager(
    sensor_path="/sys/class/thermal/thermal_zone0/temp",  # Linux
    warning_temp_c=75,
    critical_temp_c=85,
    cooldown_strategy="exponential_backoff",
)

# Callback when temperature changes
thermal.on_warning(lambda t: logger.warning(f"Temp warning: {t}°C"))
thermal.on_critical(lambda t: executor.pause())
thermal.on_normal(lambda t: executor.resume())

await thermal.start_monitoring()
```

## Memory Guards

Prevent OOM (Out of Memory) crashes:

```python
from cemaf.throttling import MemoryGuard

guard = MemoryGuard(
    soft_limit_mb=3072,    # Start evicting at 3GB
    hard_limit_mb=3584,    # Block new allocations at 3.5GB
    oom_score_adj=1000,    # Make process OOM-killable first
)

# Wrap context operations
@guard.protected
async def process_large_document(doc):
    chunks = split_document(doc)
    results = []
    for chunk in chunks:
        guard.check()  # Raises if near limit
        result = await process_chunk(chunk)
        results.append(result)
    return results

# Or use streaming
async for chunk in guard.stream_safe(large_iterator):
    await process_chunk(chunk)
```

### Eviction Strategies

```python
from cemaf.throttling import EvictionStrategy

guard = MemoryGuard(
    eviction_strategy=EvictionStrategy.LRU,  # Least Recently Used
    # OR
    # eviction_strategy=EvictionStrategy.LFU,  # Least Frequently Used
    # eviction_strategy=EvictionStrategy.PRIORITY,  # Lowest priority first
    # eviction_strategy=EvictionStrategy.SIZE,  # Largest first
)
```

## Disk I/O Throttling

Prevent SD card wear and I/O starvation:

```python
from cemaf.throttling import DiskThrottler

disk = DiskThrottler(
    max_write_mbps=10,       # Limit write speed
    max_read_mbps=50,        # Limit read speed
    io_scheduler="deadline", # Prefer latency over throughput
)

# Wrap file operations
async with disk.throttled_write("/path/to/file") as f:
    await f.write(data)
```

## Composite Resource Guard

Combine multiple guards:

```python
from cemaf.throttling import CompositeGuard

guard = CompositeGuard(
    guards=[
        CPUGuard(threshold=90),
        MemoryGuard(soft_limit_mb=3072),
        ThermalGuard(critical_temp_c=85),
        DiskGuard(threshold=95),
    ],
    strategy="any",  # Trigger if ANY guard trips
    # OR
    # strategy="all",  # Trigger if ALL guards trip
)

async with guard.protected():
    result = await executor.run(dag, context)
```

## Adaptive Execution

Adjust behavior based on resource availability:

```python
from cemaf.throttling import AdaptiveExecutor

executor = AdaptiveExecutor(
    base_executor=DAGExecutor(node_executor=my_executor),
    adaptations={
        # Low resources: reduce parallelism
        "low_memory": {"max_parallel": 1},

        # High temp: add delays
        "high_temp": {"inter_node_delay_ms": 100},

        # Low disk: disable logging
        "low_disk": {"enable_logging": False},
    },
)

# Executor adapts automatically
result = await executor.run(dag, context)
print(f"Mode: {executor.current_mode}")  # "normal", "low_memory", etc.
```

## Metrics & Monitoring

```python
from cemaf.throttling import ResourceMonitor

monitor = ResourceMonitor(
    metrics_path="/var/cemaf/metrics",
    export_interval_seconds=60,
)

# Start monitoring
await monitor.start()

# Get current stats
stats = monitor.current()
print(f"CPU: {stats.cpu_percent}%")
print(f"Memory: {stats.memory_mb} / {stats.memory_total_mb} MB")
print(f"Temp: {stats.temperature_c}°C")
print(f"Disk: {stats.disk_percent}%")

# Historical data
history = monitor.history(hours=24)
for point in history:
    print(f"{point.timestamp}: CPU {point.cpu_percent}%")
```

## Factory Functions

```python
from cemaf.throttling.factories import (
    create_resource_guard,
    create_context_pager,
    create_adaptive_executor,
)

# DI-friendly factories
guard = create_resource_guard(
    config=ResourceConfig(
        cpu_threshold=90,
        memory_threshold=85,
        temp_threshold=80,
    ),
    # Override specific components
    overrides={
        "memory_guard": MyCustomMemoryGuard(),
    },
)

# From environment
guard = create_resource_guard_from_config()
# Reads: CEMAF_RESOURCE_CPU_THRESHOLD, CEMAF_RESOURCE_MEMORY_THRESHOLD, etc.
```

## Best Practices

1. **Set conservative thresholds** - Leave headroom for OS and other processes
2. **Monitor before deploying** - Profile actual resource usage in production
3. **Use paging for large contexts** - Don't assume everything fits in RAM
4. **Handle throttle gracefully** - Show user-friendly messages during pauses
5. **Log resource events** - Track when guards trigger for debugging

## Example: Raspberry Pi Agent

```python
from cemaf.throttling import (
    ResourceCircuitBreaker,
    ContextPager,
    ThermalManager,
    AdaptiveExecutor,
)

async def create_pi_agent():
    # Circuit breaker for Pi 4 limits
    breaker = ResourceCircuitBreaker(
        thresholds={
            "cpu_percent": 80,      # Pi throttles at 85°C
            "memory_percent": 75,   # Leave room for OS
            "temperature_c": 75,    # Thermal margin
        },
    )

    # Page context to SD card
    pager = ContextPager(
        memory_limit_mb=256,
        storage_path="/tmp/cemaf_pages",
    )

    # Thermal monitoring
    thermal = ThermalManager(
        sensor_path="/sys/class/thermal/thermal_zone0/temp",
    )

    # Adaptive execution
    executor = AdaptiveExecutor(
        base_executor=DAGExecutor(node_executor=my_executor),
        resource_breaker=breaker,
        context_pager=pager,
    )

    await thermal.start_monitoring()

    return executor

# Run with resource awareness
executor = await create_pi_agent()
with executor.guarded():
    result = await executor.run(dag, paged_context)
```
