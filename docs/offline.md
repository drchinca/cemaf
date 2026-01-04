# Offline & Store-and-Forward

Edge devices lose connectivity. CEMAF keeps working.

This module provides **offline-first** capabilities for agents running on resource-constrained, intermittently-connected devices.

## The Edge Reality

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Typical Edge Scenario                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   IoT Device (Jetson Nano / Raspberry Pi)                          │
│   ├── Runs for months                                               │
│   ├── WiFi drops every few hours                                   │
│   ├── 4G modem has data caps                                       │
│   └── Must keep processing during outages                          │
│                                                                     │
│   Without CEMAF Offline:                                            │
│   ├── Agent crashes on network timeout                             │
│   ├── Loses all context when reconnecting                          │
│   └── RunRecords lost forever                                       │
│                                                                     │
│   With CEMAF Offline:                                               │
│   ├── Falls back to local LLM (Llama.cpp)                          │
│   ├── Queues RunRecords to disk                                    │
│   ├── Syncs when connectivity returns                              │
│   └── Zero data loss, continuous operation                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## OfflineQueue for RunLogger

The `OfflineQueue` buffers RunRecords when the network is unavailable:

```python
from cemaf.offline import OfflineQueue, OfflineRunLogger
from cemaf.observability import InMemoryRunLogger

# Wrap any RunLogger with offline capability
base_logger = InMemoryRunLogger()
offline_queue = OfflineQueue(
    storage_path="/var/cemaf/offline_queue",
    max_queue_size_mb=100,
    sync_batch_size=50,
)

logger = OfflineRunLogger(
    primary_logger=CloudRunLogger(api_url="https://api.example.com"),
    fallback_logger=base_logger,
    offline_queue=offline_queue,
)

# Use normally - offline handling is automatic
logger.start_run(run_id="run_001", dag_name="sensor_dag")
# ... agent execution ...
logger.end_run(final_context=ctx, success=True)

# If offline: queued to disk
# When online: automatically synced
```

### Queue Storage Format

```
/var/cemaf/offline_queue/
├── pending/
│   ├── 2024-01-15T10:30:00_run_001.json
│   ├── 2024-01-15T10:35:00_run_002.json
│   └── 2024-01-15T10:40:00_run_003.json
├── synced/
│   └── (moved here after successful sync)
└── failed/
    └── (moved here after max retries)
```

### Sync Behavior

```python
from cemaf.offline import SyncManager

sync_manager = SyncManager(
    queue=offline_queue,
    sync_interval_seconds=60,       # Check every minute
    max_retries=3,                   # Per record
    backoff_strategy="exponential",  # 1s, 2s, 4s...
    batch_size=50,                   # Records per sync
)

# Start background sync (non-blocking)
await sync_manager.start()

# Manual sync trigger
await sync_manager.sync_now()

# Check status
status = sync_manager.status()
print(f"Pending: {status.pending_count}")
print(f"Last sync: {status.last_sync_at}")
print(f"Online: {status.is_online}")
```

## Offline LLM Fallback

When cloud LLM is unreachable, fall back to local model:

```python
from cemaf.offline import OfflineLLMClient
from cemaf.llm import LLMClient

# Primary: Cloud LLM (GPT-4, Claude)
# Fallback: Local LLM (Llama.cpp, Ollama)
llm_client = OfflineLLMClient(
    primary=CloudLLMClient(api_key="..."),
    fallback=LocalLLMClient(model_path="/models/llama-3-8b.gguf"),

    # When to fall back
    timeout_seconds=5.0,
    max_retries=2,

    # Budget adjustment for smaller model
    fallback_budget_ratio=0.5,  # 8K instead of 16K
)

# Automatic fallback
response = await llm_client.complete(messages, budget)
print(f"Used: {'primary' if response.metadata.get('source') == 'primary' else 'fallback'}")
```

### Capability Degradation

```python
from cemaf.offline import CapabilityManager

capabilities = CapabilityManager(
    online_capabilities={
        "vision": True,
        "function_calling": True,
        "max_tokens": 128000,
    },
    offline_capabilities={
        "vision": False,           # Local model can't do vision
        "function_calling": True,  # Llama supports this
        "max_tokens": 8000,        # Smaller context
    },
)

# Agent adapts based on connectivity
if capabilities.is_available("vision"):
    result = await process_image(image)
else:
    result = await process_image_description(image_metadata)
```

## Offline Tool Execution

Tools can specify offline behavior:

```python
from cemaf.tools import Tool
from cemaf.offline import OfflinePolicy

@tool(
    offline_policy=OfflinePolicy.QUEUE,  # Queue for later
    # OR
    # offline_policy=OfflinePolicy.SKIP,  # Skip silently
    # offline_policy=OfflinePolicy.LOCAL_FALLBACK,  # Use cached/local
    # offline_policy=OfflinePolicy.FAIL,  # Raise error
)
async def send_notification(message: str) -> dict:
    """Send push notification to user."""
    return await push_service.send(message)

@tool(
    offline_policy=OfflinePolicy.LOCAL_FALLBACK,
    local_cache_ttl=3600,  # Use cached results for 1 hour
)
async def get_weather(location: str) -> dict:
    """Get current weather."""
    return await weather_api.get(location)
```

### Tool Queue

```python
from cemaf.offline import ToolQueue

tool_queue = ToolQueue(
    storage_path="/var/cemaf/tool_queue",
    max_queue_size=1000,
)

# Queued tools execute when online
await tool_queue.start_processor(
    on_success=lambda result: logger.info(f"Executed: {result}"),
    on_failure=lambda error: logger.error(f"Failed: {error}"),
)
```

## Context Persistence

Save context to disk for crash recovery:

```python
from cemaf.offline import ContextPersistence

persistence = ContextPersistence(
    storage_path="/var/cemaf/context",
    checkpoint_interval=10,  # Every 10 patches
)

# Auto-checkpoint during execution
executor = DAGExecutor(
    node_executor=my_executor,
    context_persistence=persistence,
)

# On crash/restart, recover from checkpoint
recovered_context = await persistence.recover_latest()
if recovered_context:
    result = await executor.run(dag, initial_context=recovered_context)
```

## Connectivity Detection

```python
from cemaf.offline import ConnectivityMonitor

monitor = ConnectivityMonitor(
    check_urls=["https://api.example.com/health"],
    check_interval_seconds=30,
    timeout_seconds=5,
)

# Event-driven
monitor.on_offline(lambda: logger.warning("Gone offline"))
monitor.on_online(lambda: sync_manager.sync_now())

# Polling
if monitor.is_online:
    await cloud_llm.complete(messages)
else:
    await local_llm.complete(messages)
```

## Data Prioritization

When bandwidth is limited, prioritize what syncs first:

```python
from cemaf.offline import SyncPrioritizer

prioritizer = SyncPrioritizer(
    rules=[
        # Critical runs first
        ("priority", lambda r: 100 if r.metadata.get("critical") else 0),

        # Recent over old
        ("recency", lambda r: 50 / max(1, r.age_hours)),

        # Small records first (faster sync)
        ("size", lambda r: 10 if r.size_kb < 10 else 0),
    ],
)

sync_manager = SyncManager(
    queue=offline_queue,
    prioritizer=prioritizer,
)
```

## Bandwidth Management

```python
from cemaf.offline import BandwidthManager

bandwidth = BandwidthManager(
    daily_limit_mb=100,       # Data cap
    rate_limit_kbps=50,       # Throttle speed
    priority_reserve_mb=20,   # Reserve for critical
)

# Sync respects bandwidth limits
sync_manager = SyncManager(
    queue=offline_queue,
    bandwidth_manager=bandwidth,
)

# Check before large operations
if bandwidth.can_send(size_kb=500):
    await sync_large_record(record)
else:
    await sync_summary_only(record)
```

## Factory Functions

```python
from cemaf.offline.factories import (
    create_offline_logger,
    create_offline_llm_client,
    create_sync_manager,
)

# DI-friendly factories
logger = create_offline_logger(
    primary_logger=my_cloud_logger,    # Inject your logger
    fallback_logger=my_local_logger,   # Inject fallback
    config=OfflineConfig(              # Or use defaults
        storage_path="/var/cemaf/offline",
        max_queue_size_mb=100,
    ),
)

# From environment
logger = create_offline_logger_from_config()
# Reads: CEMAF_OFFLINE_STORAGE_PATH, CEMAF_OFFLINE_MAX_QUEUE_MB
```

## Best Practices

1. **Always plan for offline** - Edge devices *will* lose connectivity
2. **Size your queue** - Calculate: `max_offline_hours * runs_per_hour * avg_record_size`
3. **Degrade gracefully** - Have fallback behavior for every online-dependent feature
4. **Monitor sync status** - Alert when queue grows too large
5. **Test offline scenarios** - Include network failure in your test suite

## Example: IoT Sensor Agent

```python
from cemaf.offline import (
    OfflineRunLogger,
    OfflineLLMClient,
    SyncManager,
    ContextPersistence,
)

# Full offline-capable setup
async def create_edge_agent():
    # Offline-capable logger
    logger = OfflineRunLogger(
        primary_logger=CloudRunLogger(api_url=CLOUD_URL),
        fallback_logger=InMemoryRunLogger(),
        offline_queue=OfflineQueue(storage_path="/data/queue"),
    )

    # Offline-capable LLM
    llm = OfflineLLMClient(
        primary=CloudLLMClient(api_key=API_KEY),
        fallback=LlamaCppClient(model_path="/models/llama3-8b.gguf"),
    )

    # Context persistence for crash recovery
    persistence = ContextPersistence(storage_path="/data/context")

    # Background sync
    sync = SyncManager(queue=logger.offline_queue)
    await sync.start()

    # Create executor
    executor = DAGExecutor(
        node_executor=LLMNodeExecutor(llm),
        run_logger=logger,
        context_persistence=persistence,
    )

    return executor, sync

# Runs continuously, handles offline gracefully
executor, sync = await create_edge_agent()
while True:
    context = await persistence.recover_latest() or Context()
    context = context.set("sensor_data", read_sensors())
    result = await executor.run(sensor_dag, context)
    await asyncio.sleep(60)
```
