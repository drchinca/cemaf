# Cache

Caching with TTL and eviction policies.

## Cache Architecture

```mermaid
flowchart TB
    subgraph Cache Store
        STORE[CacheStore<br/>Protocol]
        INMEM[InMemoryCache<br/>Implementation]
    end

    subgraph Policies
        TTL[TTL<br/>Time-based expiry]
        SIZE[Max Size<br/>Capacity limit]
        LRU[LRU<br/>Least recently used]
    end

    subgraph Decorators
        CACHED[@cached<br/>Function decorator]
        KEY[Key Generation<br/>Args to key]
    end

    STORE --> INMEM
    TTL --> INMEM
    SIZE --> INMEM
    LRU --> INMEM
    CACHED --> STORE
    KEY --> CACHED
```

## Cache Flow

```mermaid
sequenceDiagram
    participant Caller
    participant Decorator as @cached
    participant Cache as CacheStore
    participant Function

    Caller->>Decorator: call(args)
    Decorator->>Cache: get(key)

    alt Cache Hit
        Cache-->>Decorator: cached_value
        Decorator-->>Caller: cached_value
    else Cache Miss
        Cache-->>Decorator: None
        Decorator->>Function: execute(args)
        Function-->>Decorator: result
        Decorator->>Cache: set(key, result, ttl)
        Decorator-->>Caller: result
    end
```

## Cache Store

```python
from cemaf.cache.stores import InMemoryCache

cache = InMemoryCache(max_size=100, default_ttl=3600)

# Set with TTL
await cache.set("key", "value", ttl_seconds=1800)

# Get
value = await cache.get("key")

# Delete
await cache.delete("key")
```

## Factory Registry

Cache backends are selected through `cache_registry`. Built-ins include
`memory` and `ttl`; applications can register Redis, Memcached, or other
stores without editing CEMAF.

```python
from cemaf.cache import Cache, cache_registry, create_cache

def create_redis_cache(**kwargs) -> Cache:
    return RedisCache(
        url=kwargs["redis_url"],
        max_size=kwargs["max_size"],
    )

cache_registry.register(
    backend="redis",
    factory=create_redis_cache,
)

cache = create_cache(
    backend="redis",
    redis_url="redis://localhost:6379",
)
```

## Cached Decorator

```python
from cemaf.cache.decorators import cached

@cached(ttl_seconds=3600)
async def expensive_operation(arg: str) -> dict:
    # Expensive computation
    return {"result": "data"}
```
