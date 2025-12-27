# Cache

Caching with TTL and eviction policies.

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

## Cached Decorator

```python
from cemaf.cache.decorators import cached

@cached(ttl_seconds=3600)
async def expensive_operation(arg: str) -> dict:
    # Expensive computation
    return {"result": "data"}
```

