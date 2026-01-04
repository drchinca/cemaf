# State Synchronization

When edge agents reconnect, their local context must merge with the cloud. CEMAF makes this deterministic.

## The Sync Challenge

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Distributed Context Problem                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Cloud Context                    Edge Context                     │
│   ┌─────────────────┐             ┌─────────────────┐              │
│   │ user.name: Bob  │             │ user.name: Alice│   CONFLICT   │
│   │ settings.theme: │             │ settings.theme: │              │
│   │   dark          │             │   dark          │   No conflict │
│   │ data.count: 100 │             │ data.count: 150 │   CONFLICT   │
│   └─────────────────┘             └─────────────────┘              │
│                                                                     │
│   Question: What is the final merged state?                        │
│                                                                     │
│   Options:                                                          │
│   1. Last-Write-Wins (LWW) - Simple, may lose data                 │
│   2. CRDT - Complex, preserves all changes                         │
│   3. Custom Resolver - Domain-specific merge logic                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Sync Strategies

### Last-Write-Wins (LWW)

Simple timestamp-based resolution:

```python
from cemaf.sync import LWWSyncStrategy

strategy = LWWSyncStrategy(
    timestamp_field="_modified_at",
    tie_breaker="cloud",  # Prefer cloud on exact tie
)

syncer = ContextSyncer(strategy=strategy)

# Merge edge changes with cloud
merged = await syncer.sync(
    local=edge_context,
    remote=cloud_context,
)
```

### LWW with Tombstones

Track deletions across sync boundaries:

```python
from cemaf.sync import LWWWithTombstones

strategy = LWWWithTombstones(
    tombstone_ttl_hours=24,  # Keep deletion markers for 24h
)

# Deleted on edge, modified on cloud
edge_context = edge_context.delete("user.temp_data")

# Sync preserves deletion intent
merged = await syncer.sync(local=edge_context, remote=cloud_context)
assert merged.get("user.temp_data") is None  # Deleted wins (if more recent)
```

### CRDT-Based Sync

Conflict-free replicated data types for eventual consistency:

```python
from cemaf.sync import CRDTSyncStrategy

strategy = CRDTSyncStrategy(
    type_mappings={
        "counter": "g_counter",    # Grow-only counter
        "set": "or_set",           # Observed-Remove Set
        "register": "lww_register", # LWW Register
        "map": "or_map",           # Observed-Remove Map
    },
)

syncer = ContextSyncer(strategy=strategy)
```

#### Supported CRDTs

| Type | Use Case | Merge Behavior |
|------|----------|----------------|
| G-Counter | Counts (views, clicks) | Sum of all increments |
| PN-Counter | Counts with decrements | Sum of increments minus decrements |
| G-Set | Tags, labels | Union of all additions |
| OR-Set | Mutable collections | Add/remove with causality |
| LWW-Register | Single values | Last write wins |
| OR-Map | Nested structures | Recursive CRDT merge |

```python
from cemaf.sync.crdt import GCounter, ORSet, LWWRegister

# Counter: tracks views across devices
views = GCounter(node_id="edge_001")
views.increment(5)

# Set: tracks user tags
tags = ORSet(node_id="edge_001")
tags.add("important")
tags.remove("draft")

# Register: single value with LWW
status = LWWRegister(node_id="edge_001")
status.set("active")
```

### Custom Resolver

Domain-specific merge logic:

```python
from cemaf.sync import CustomSyncStrategy, ConflictResolver

class MyResolver(ConflictResolver):
    def resolve(
        self,
        key: str,
        local_value: Any,
        remote_value: Any,
        local_meta: dict,
        remote_meta: dict,
    ) -> Any:
        # Counters: sum them
        if key.endswith(".count"):
            local_delta = local_value - local_meta.get("base_value", 0)
            remote_delta = remote_value - remote_meta.get("base_value", 0)
            return local_meta.get("base_value", 0) + local_delta + remote_delta

        # Lists: merge unique items
        if isinstance(local_value, list) and isinstance(remote_value, list):
            return list(set(local_value + remote_value))

        # Default: prefer remote (cloud authority)
        return remote_value

strategy = CustomSyncStrategy(resolver=MyResolver())
```

## Sync Protocol

### Vector Clocks

Track causality across distributed contexts:

```python
from cemaf.sync import VectorClock

# Each node maintains a clock
edge_clock = VectorClock(node_id="edge_001")
cloud_clock = VectorClock(node_id="cloud")

# Increment on local change
edge_clock.increment()
context = context.set("data", value, clock=edge_clock)

# Compare causality
if edge_clock.happened_before(cloud_clock):
    # Edge change is older - cloud wins
    pass
elif cloud_clock.happened_before(edge_clock):
    # Cloud change is older - edge wins
    pass
else:
    # Concurrent changes - need resolution
    pass
```

### Sync Workflow

```python
from cemaf.sync import SyncOrchestrator

orchestrator = SyncOrchestrator(
    strategy=LWWSyncStrategy(),
    transport=HTTPSyncTransport(base_url="https://api.example.com"),
)

# Full sync workflow
async def sync_with_cloud():
    # 1. Get remote state
    remote = await orchestrator.fetch_remote()

    # 2. Compute diff
    diff = orchestrator.compute_diff(local=edge_context, remote=remote)

    # 3. Resolve conflicts
    resolved = await orchestrator.resolve_conflicts(diff)

    # 4. Apply locally
    merged_local = edge_context.apply_patches(resolved.local_patches)

    # 5. Push to remote
    await orchestrator.push_changes(resolved.remote_patches)

    # 6. Confirm sync
    await orchestrator.confirm(resolved.sync_id)

    return merged_local
```

## Conflict Detection

Identify conflicts before resolution:

```python
from cemaf.sync import ConflictDetector

detector = ConflictDetector()

conflicts = detector.detect(
    local=edge_context,
    remote=cloud_context,
    base=last_synced_context,  # Common ancestor
)

for conflict in conflicts:
    print(f"Key: {conflict.key}")
    print(f"Local: {conflict.local_value}")
    print(f"Remote: {conflict.remote_value}")
    print(f"Type: {conflict.conflict_type}")  # "modify-modify", "delete-modify", etc.
```

### Conflict Types

| Type | Description | Default Resolution |
|------|-------------|-------------------|
| modify-modify | Both changed same key | LWW or custom |
| delete-modify | One deleted, one modified | Prefer deletion |
| add-add | Both added same key | LWW or merge |
| type-change | Types differ (str→int) | Prefer remote |

## Sync Events

React to sync lifecycle:

```python
from cemaf.sync import SyncEventBus

events = SyncEventBus()

@events.on("sync.started")
async def on_sync_start(sync_id: str):
    logger.info(f"Sync started: {sync_id}")

@events.on("conflict.detected")
async def on_conflict(conflict: Conflict):
    logger.warning(f"Conflict on {conflict.key}")

@events.on("sync.completed")
async def on_sync_complete(result: SyncResult):
    logger.info(f"Sync complete: {result.changes_applied} changes")

@events.on("sync.failed")
async def on_sync_failed(error: SyncError):
    alert(f"Sync failed: {error}")
```

## Offline-to-Online Sync

Integrates with offline module:

```python
from cemaf.sync import SyncManager
from cemaf.offline import OfflineQueue

sync_manager = SyncManager(
    strategy=LWWSyncStrategy(),
    offline_queue=OfflineQueue(storage_path="/data/queue"),
)

# When online, sync queued changes
await sync_manager.sync_pending()

# Continuous sync
await sync_manager.start_continuous(
    interval_seconds=60,
    on_conflict=lambda c: resolver.resolve(c),
)
```

## Partial Sync

Sync only specific paths:

```python
syncer = ContextSyncer(strategy=strategy)

# Only sync user preferences
merged = await syncer.sync(
    local=edge_context,
    remote=cloud_context,
    paths=["user.preferences", "user.settings"],
)

# Exclude large/ephemeral data
merged = await syncer.sync(
    local=edge_context,
    remote=cloud_context,
    exclude_paths=["cache", "temp", "large_documents"],
)
```

## Sync Metadata

Track sync history:

```python
from cemaf.sync import SyncMetadata

metadata = SyncMetadata(storage_path="/data/sync_meta")

# Record sync
await metadata.record_sync(
    sync_id="sync_001",
    local_version=edge_context.version,
    remote_version=cloud_context.version,
    conflicts_resolved=3,
)

# Get last sync
last = await metadata.get_last_sync()
print(f"Last sync: {last.timestamp}, version: {last.remote_version}")

# Get sync history
history = await metadata.get_history(limit=10)
```

## Factory Functions

```python
from cemaf.sync.factories import (
    create_syncer,
    create_sync_strategy,
    create_sync_manager,
)

# DI-friendly
syncer = create_syncer(
    strategy=LWWSyncStrategy(),
    transport=my_transport,       # Inject custom transport
    conflict_resolver=my_resolver, # Inject custom resolver
)

# From environment
syncer = create_syncer_from_config()
# Reads: CEMAF_SYNC_STRATEGY, CEMAF_SYNC_TRANSPORT_URL, etc.
```

## Best Practices

1. **Choose the right strategy** - LWW for simple cases, CRDT for high-conflict scenarios
2. **Track causality** - Vector clocks prevent lost updates
3. **Sync incrementally** - Don't sync entire context every time
4. **Handle failures gracefully** - Retry with exponential backoff
5. **Monitor conflicts** - High conflict rate may indicate design issues

## Example: Multi-Device Agent

```python
from cemaf.sync import (
    ContextSyncer,
    LWWSyncStrategy,
    SyncManager,
    VectorClock,
)

class MultiDeviceAgent:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.clock = VectorClock(node_id=node_id)
        self.syncer = ContextSyncer(
            strategy=LWWSyncStrategy(tie_breaker="higher_node_id"),
        )
        self.sync_manager = SyncManager(
            syncer=self.syncer,
            transport=WebSocketTransport(url="wss://sync.example.com"),
        )

    async def update_context(self, key: str, value: Any):
        """Update with vector clock tracking."""
        self.clock.increment()
        self.context = self.context.set(
            key, value,
            metadata={"_vclock": self.clock.to_dict()},
        )
        await self.sync_manager.notify_change(key)

    async def run(self, dag: DAG):
        """Run with automatic sync."""
        # Sync before execution
        self.context = await self.sync_manager.sync(self.context)

        # Execute
        result = await self.executor.run(dag, self.context)

        # Sync after execution
        self.context = await self.sync_manager.sync(result.final_context)

        return result

# Usage
agent = MultiDeviceAgent(node_id="edge_001")
await agent.sync_manager.start_continuous()
result = await agent.run(my_dag)
```
