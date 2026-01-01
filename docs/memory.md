# Memory Management

CEMAF provides scoped memory management for different persistence needs.

## Memory Architecture

```mermaid
flowchart TB
    subgraph Memory Store
        STORE[MemoryStore<br/>Protocol]
        INMEM[InMemoryStore<br/>Implementation]
    end

    subgraph Scopes
        SESSION[SESSION<br/>Request lifetime]
        PROJECT[PROJECT<br/>Days]
        BRAND[BRAND<br/>Permanent]
        PERSONAE[PERSONAE<br/>Permanent]
    end

    subgraph Features
        TTL[TTL<br/>Auto-expiration]
        HOOKS[Hooks<br/>Redaction, Serialization]
        SEARCH[Search<br/>Query memory]
    end

    STORE --> INMEM
    INMEM --> SESSION
    INMEM --> PROJECT
    INMEM --> BRAND
    INMEM --> PERSONAE
    TTL --> STORE
    HOOKS --> STORE
    SEARCH --> STORE
```

## Memory Operations Flow

```mermaid
sequenceDiagram
    participant Client
    participant Store as MemoryStore
    participant Hooks
    participant Storage

    Client->>Store: set(key, value, scope, ttl)
    Store->>Hooks: Apply redaction hook
    Hooks-->>Store: Redacted value
    Store->>Hooks: Apply serialization hook
    Hooks-->>Store: Serialized value
    Store->>Storage: Store item

    Client->>Store: get(key, scope)
    Store->>Storage: Retrieve item
    Storage-->>Store: MemoryItem

    alt Item expired
        Store->>Storage: Delete item
        Store-->>Client: None
    else Item valid
        Store-->>Client: MemoryItem
    end
```

## Memory Scopes

| Scope      | Persistence | Use Case           |
| ---------- | ----------- | ------------------ |
| `SESSION`  | Request     | Conversation state |
| `PROJECT`  | Days        | Task context       |
| `BRAND`    | Permanent   | Brand guidelines   |
| `PERSONAE` | Permanent   | User preferences   |

## Memory Store

```python
from cemaf.memory.base import MemoryStore, InMemoryStore
from cemaf.core.enums import MemoryScope

store = InMemoryStore()

# Store memory
await store.set(
    key="user_preference",
    value={"theme": "dark"},
    scope=MemoryScope.PERSONAE
)

# Retrieve memory
item = await store.get("user_preference", scope=MemoryScope.PERSONAE)

# List by scope
items = await store.list_by_scope(MemoryScope.PERSONAE)

# Search
results = await store.search("preference", scope=MemoryScope.PERSONAE)
```

## Memory Item

```python
from cemaf.memory.base import MemoryItem

item = MemoryItem(
    key="key",
    value={"data": "value"},
    scope=MemoryScope.PROJECT,
    metadata={"source": "user"}
)

# Full key includes scope
full_key = item.full_key  # "PROJECT:key"
```
