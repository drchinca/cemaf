# Cache Module: Response Caching Strategies

## Overview

The `cache` module provides **time-aware response caching** with TTL (Time-To-Live) support, enabling efficient reuse of expensive computations like LLM calls, database queries, and API responses.

**Key Purpose**: Reduce latency and cost of repeated operations
**Main Components**: `Cache`, `InMemoryCache`, `TTLCache`
**When to Use**: Cache deterministic operations with repeatable inputs

---

## Core Concepts

### Cache Abstraction

```python
from cemaf.cache import Cache

class Cache(Protocol):
    """Protocol for cache backends."""

    async def get(self, key: str) -> Any | None:
        """Retrieve cached value."""
        ...

    async def set(self, key: str, value: Any, ttl: int | None = None):
        """Store value with optional TTL."""
        ...

    async def delete(self, key: str):
        """Remove cached value."""
        ...

    async def clear(self):
        """Clear entire cache."""
        ...
```

### TTL (Time-To-Live)

```python
# Cache expires after TTL seconds
cache = TTLCache(ttl_seconds=3600)  # 1 hour

# Set with custom TTL
await cache.set("key", "value", ttl=1800)  # 30 minutes

# Get returns None if expired
value = await cache.get("key")  # None if TTL passed
```

### Cache Keys

```python
# Generate deterministic cache key from inputs
def make_cache_key(query: str, model: str) -> str:
    """Create cache key from inputs."""
    import hashlib
    content = f"{query}:{model}"
    return hashlib.md5(content.encode()).hexdigest()

# Use in caching
key = make_cache_key(query, "claude-3-sonnet")
```

---

## Usage Examples

### Basic LLM Caching

```python
from cemaf.cache import TTLCache
from cemaf.llm import LLMClient, Message, Role

cache = TTLCache(ttl_seconds=3600)

async def cached_completion(
    llm: LLMClient,
    messages: list[Message],
) -> str:
    """Cache LLM completions."""
    # Create key from messages
    key = hash(tuple((m.role, m.content) for m in messages))

    # Check cache
    cached = await cache.get(str(key))
    if cached:
        return cached

    # Execute and cache
    result = await llm.complete(messages)
    await cache.set(str(key), result.text, ttl=3600)
    return result.text
```

### Tool Result Caching

```python
from cemaf.tools import Tool, ToolResult
from cemaf.cache import TTLCache

class CachedTool(Tool):
    def __init__(self, tool: Tool, cache: TTLCache):
        self.tool = tool
        self.cache = cache

    async def execute(self, **kwargs) -> ToolResult:
        """Execute with caching."""
        # Create key from all arguments
        key = self._make_key(**kwargs)

        # Check cache
        cached = await self.cache.get(key)
        if cached:
            return ToolResult(success=True, data=cached)

        # Execute tool
        result = await self.tool.execute(**kwargs)

        # Cache if successful
        if result.success:
            await self.cache.set(key, result.data, ttl=3600)

        return result

    def _make_key(self, **kwargs) -> str:
        import hashlib
        content = str(sorted(kwargs.items()))
        return hashlib.md5(content.encode()).hexdigest()
```

### Database Query Caching

```python
from cemaf.cache import TTLCache

cache = TTLCache(ttl_seconds=300)  # 5 minutes

async def get_user_cached(user_id: int) -> dict:
    """Get user with caching."""
    key = f"user:{user_id}"

    # Check cache first
    cached = await cache.get(key)
    if cached:
        return cached

    # Query database
    user = await db.get_user(user_id)

    # Cache result
    await cache.set(key, user)

    return user
```

### Anti-Pattern: Caching Non-Deterministic Operations

```python
# ❌ WRONG - Random number generator is non-deterministic
cache = TTLCache(ttl_seconds=3600)

async def get_random_number():
    key = "random"
    cached = await cache.get(key)
    if cached:
        return cached

    number = random.randint(1, 100)
    await cache.set(key, number)
    return number

# Subsequent calls return SAME number (cached)
# But random should be different each time!

# ✅ RIGHT - Only cache deterministic functions
async def get_config(name: str):
    key = f"config:{name}"
    cached = await cache.get(key)
    if cached:
        return cached

    config = await db.get_config(name)
    await cache.set(key, config)
    return config

# Same input always returns same config (correct)
```

---

## Integration

### With LLM Calls

```python
from cemaf.cache import TTLCache
from functools import wraps

class LLMWithCache:
    def __init__(self, llm: LLMClient, cache: TTLCache):
        self.llm = llm
        self.cache = cache

    async def complete(self, messages: list[Message], **kwargs):
        """LLM complete with caching."""
        # Create key from messages
        key = self._cache_key(messages, **kwargs)

        # Check cache
        cached = await self.cache.get(key)
        if cached:
            return cached

        # Execute
        result = await self.llm.complete(messages, **kwargs)

        # Cache
        await self.cache.set(key, result.text, ttl=3600)

        return result

    def _cache_key(self, messages, **kwargs):
        import hashlib
        content = str(messages) + str(sorted(kwargs.items()))
        return hashlib.md5(content.encode()).hexdigest()
```

### With RLM

```python
from cemaf.rlm import RLMQueryTool
from cemaf.cache import TTLCache

class CachedRLM:
    def __init__(self, rlm: RLMQueryTool, cache: TTLCache):
        self.rlm = rlm
        self.cache = cache

    async def execute(self, instruction: str, content: str, **kwargs):
        """RLM query with result caching."""
        # For large documents, cache is very valuable
        key = f"rlm:{hash(instruction)}:{hash(content[:1000])}"

        cached = await self.cache.get(key)
        if cached:
            return cached

        result = await self.rlm.execute(
            instruction=instruction,
            content=content,
            **kwargs,
        )

        await self.cache.set(key, result, ttl=3600)
        return result
```

### With Observability

```python
from cemaf.cache import TTLCache
from cemaf.observability import Logger

logger = Logger()

class ObservableCache(TTLCache):
    async def get(self, key: str):
        value = await super().get(key)
        if value:
            logger.info("Cache hit", extra={"key": key})
        else:
            logger.info("Cache miss", extra={"key": key})
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None):
        await super().set(key, value, ttl)
        logger.debug("Cache set", extra={"key": key, "ttl": ttl})
```

---

## API Reference

### Cache Protocol

```python
class Cache(Protocol):
    async def get(self, key: str) -> Any | None:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ):
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (None = forever)
        """

    async def delete(self, key: str):
        """Delete cached value."""

    async def clear(self):
        """Clear all cache entries."""
```

### TTLCache

```python
class TTLCache:
    def __init__(self, ttl_seconds: int = 3600):
        """Initialize TTL cache.

        Args:
            ttl_seconds: Default TTL for entries (default 1 hour)
        """

    async def get(self, key: str) -> Any | None:
        """Get with automatic expiration."""
        # Returns None if entry expired

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ):
        """Set with TTL."""
        # Uses provided ttl or default ttl_seconds

    async def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self.data),
        }
```

---

## Best Practices

### 1. Choose Appropriate TTL

```python
# For stable data (configs, static content)
stable_cache = TTLCache(ttl_seconds=86400)  # 1 day

# For semi-stable (user profiles)
medium_cache = TTLCache(ttl_seconds=3600)  # 1 hour

# For changing data (search results)
short_cache = TTLCache(ttl_seconds=300)  # 5 minutes

# For real-time data (not cached)
# Don't cache
```

### 2. Deterministic Cache Keys

```python
# ✅ GOOD - Deterministic from inputs
def cache_key_good(query: str, top_k: int) -> str:
    import hashlib
    content = f"{query}:{top_k}"
    return hashlib.md5(content.encode()).hexdigest()

# ❌ BAD - Uses non-deterministic data
def cache_key_bad(query: str, timestamp: float) -> str:
    # Different key each time even for same query!
    return f"{query}:{timestamp}"

# ❌ BAD - Non-deterministic order
def cache_key_bad2(filters: dict) -> str:
    # Dict order might vary
    return str(filters)

# ✅ GOOD - Sorted for determinism
def cache_key_good2(filters: dict) -> str:
    return str(sorted(filters.items()))
```

### 3. Cache Invalidation Strategy

```python
# Manual invalidation
await cache.delete(f"user:{user_id}")

# Time-based invalidation (TTL)
await cache.set(key, value, ttl=3600)

# Event-based invalidation
async def on_user_updated(user_id: int):
    await cache.delete(f"user:{user_id}")

# Clear related entries
async def clear_user_cache(user_id: int):
    await cache.delete(f"user:{user_id}")
    await cache.delete(f"user_preferences:{user_id}")
    await cache.delete(f"user_history:{user_id}")
```

### 4. Memory Management

```python
# ✅ Good - Limited cache size
cache = TTLCache(ttl_seconds=3600)
# Also implement cleanup for old entries
async def cleanup_expired():
    while True:
        await cache.cleanup_expired()
        await asyncio.sleep(3600)  # Every hour

# ❌ Bad - Unbounded growth
# Cache grows forever without cleanup
```

### 5. Cache Stampede Prevention

```python
# Problem: Multiple concurrent requests for expired key
# Solution: Lock and single computation

class StampedePreventingCache(TTLCache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.locks: dict[str, asyncio.Lock] = {}

    async def get_or_compute(self, key: str, compute_func):
        """Get from cache or compute once."""
        # Check if already cached
        cached = await self.get(key)
        if cached:
            return cached

        # Ensure only one computation for this key
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()

        async with self.locks[key]:
            # Check again (might have been computed while waiting)
            cached = await self.get(key)
            if cached:
                return cached

            # Compute once
            value = await compute_func()
            await self.set(key, value)
            return value
```

---

## Common Patterns

### Pattern 1: Tiered Caching

```python
# In-process cache (fast, limited size)
memory_cache = TTLCache(ttl_seconds=300)  # 5 min

# Redis cache (shared, larger)
# redis_cache = RedisCache(...)

async def get_with_tiered_cache(key: str, compute_func):
    """Check memory, then redis, then compute."""
    # Check memory cache
    value = await memory_cache.get(key)
    if value:
        return value

    # Check redis
    # value = await redis_cache.get(key)
    # if value:
    #     await memory_cache.set(key, value)  # Populate local
    #     return value

    # Compute
    value = await compute_func()
    await memory_cache.set(key, value)
    # await redis_cache.set(key, value)
    return value
```

### Pattern 2: Cache Warming

```python
async def warm_cache():
    """Pre-populate cache with common queries."""
    common_queries = [
        "what is python?",
        "how to use asyncio?",
        "best practices?",
    ]

    for query in common_queries:
        result = await llm.complete([
            Message(role=Role.USER, content=query)
        ])
        key = f"llm:{hash(query)}"
        await cache.set(key, result.text, ttl=3600)

    logger.info(f"Warmed cache with {len(common_queries)} entries")
```

### Pattern 3: Conditional Caching

```python
async def smart_cache(
    instruction: str,
    content: str,
    cacheable: bool = True,
) -> dict:
    """Cache only deterministic results."""
    # Some operations shouldn't be cached
    if not cacheable:
        return await execute(instruction, content)

    key = f"{hash(instruction)}:{hash(content[:1000])}"
    cached = await cache.get(key)
    if cached:
        return cached

    result = await execute(instruction, content)
    await cache.set(key, result, ttl=3600)
    return result
```

---

## Troubleshooting

### Issue: Stale Cache Data

```python
# Problem: Cached data is outdated
# Solution: Lower TTL or use event-based invalidation

# Before: 1 day TTL (too long for changing data)
old_cache = TTLCache(ttl_seconds=86400)

# After: 5 minute TTL (more appropriate)
new_cache = TTLCache(ttl_seconds=300)

# Or use event-based invalidation
async def on_data_change(resource_id: str):
    await cache.delete(f"resource:{resource_id}")
```

### Issue: Memory Usage Growing

```python
# Problem: Cache grows unbounded
# Solution: Implement size limits or cleanup

class LimitedCache(TTLCache):
    def __init__(self, ttl_seconds: int, max_size: int):
        super().__init__(ttl_seconds)
        self.max_size = max_size

    async def set(self, key: str, value: Any, ttl: int | None = None):
        # If at capacity, evict oldest
        if len(self.data) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self.data.keys(), key=lambda k: self.data[k]['timestamp'])
            await self.delete(oldest_key)

        await super().set(key, value, ttl)
```

### Issue: Cache Not Working as Expected

```python
# Problem: Cache hits not happening
# Solution: Debug cache keys

def debug_cache_key(query: str, model: str) -> str:
    """Generate consistent cache key."""
    import hashlib

    # ❌ Problem: Inconsistent key generation
    # Different key each time for same input

    # ✅ Solution: Deterministic, logged
    content = f"{query}:{model}"
    key = hashlib.md5(content.encode()).hexdigest()

    logger.debug(f"Cache key: {key}", extra={
        "query": query,
        "model": model,
    })

    return key
```

---

## Configuration

```python
# config.yaml
cache:
  ttl_seconds: 3600
  max_entries: 10000
  cleanup_interval: 3600

  # By operation type
  llm_ttl: 3600          # LLM calls cached 1 hour
  database_ttl: 300       # DB results cached 5 min
  api_ttl: 600            # API results cached 10 min
```

---

**Related Documentation**:
- [LLM Module](./llm.md) - LLM caching patterns
- [Tools Module](./tools.md) - Tool result caching
- [RLM Module](./rlm.md) - RLM output caching
- [Observability Module](./observability.md) - Cache statistics
