# Resilience Module: Fault Tolerance Patterns

## Overview

The `resilience` module provides **production-grade fault tolerance patterns** including retry with exponential backoff, circuit breaker pattern, rate limiting, and timeout enforcement. These patterns protect CEMAF systems from cascading failures and resource exhaustion.

**Key Purpose**: Prevent transient failures from crashing systems
**Main Components**: `RetryPolicy`, `CircuitBreaker`, `RateLimiter`
**When to Use**: Wrap every external call (LLM, database, API) with resilience patterns

---

## Core Concepts

### Retry with Exponential Backoff

```python
from cemaf.resilience import RetryPolicy, RetryConfig

# Exponential backoff: 1s → 2s → 4s → 8s → 16s
config = RetryConfig(
    max_attempts=5,
    initial_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,  # Add randomness to prevent thundering herd
)

policy = RetryPolicy(config)

# Apply to function
@policy.retry
async def call_llm(messages: list[Message]) -> CompletionResult:
    return await llm.complete(messages)
```

### Circuit Breaker Pattern

```python
from cemaf.resilience import CircuitBreaker, CircuitConfig

# Fail fast after 5 consecutive errors
circuit_config = CircuitConfig(
    failure_threshold=5,
    success_threshold=2,  # Close after 2 successes
    timeout=60.0,  # Retry after 60s
)

breaker = CircuitBreaker(circuit_config)

@breaker.protect
async def query_database():
    return await db.query()
```

**States**:
- **CLOSED** (normal): Requests flow through
- **OPEN** (failing): Requests rejected immediately
- **HALF_OPEN** (testing): Allowing trial requests

### Rate Limiting

```python
from cemaf.resilience import RateLimiter

# Allow 100 requests per 60 seconds
limiter = RateLimiter(rate=100, period=60.0)

@limiter.limit
async def search_api(query: str):
    return await external_search(query)
```

---

## Usage Examples

### Basic Retry

```python
from cemaf.resilience import retry, RetryConfig

config = RetryConfig(
    max_attempts=3,
    initial_delay=0.5,
    exponential_base=2.0,
)

@retry(config)
async def fetch_data(url: str) -> dict:
    """Retry with exponential backoff."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

# Usage
try:
    data = await fetch_data("https://api.example.com/data")
except Exception as e:
    logger.error(f"Failed after retries: {e}")
```

### Circuit Breaker Protection

```python
from cemaf.resilience import CircuitBreaker, CircuitConfig

breaker = CircuitBreaker(
    CircuitConfig(
        failure_threshold=3,
        success_threshold=1,
        timeout=30.0,
    )
)

@breaker.protect
async def risky_operation():
    """Protected by circuit breaker."""
    # If this fails 3 times, circuit opens
    # Future calls fail immediately (fast-fail)
    return await external_service.call()

# Usage
try:
    result = await risky_operation()
except CircuitBreakerOpenError:
    logger.info("Circuit open, service unavailable")
    return cached_result  # Fallback
```

### Combined Retry + Circuit Breaker

```python
@retry(retry_config)
@breaker.protect
async def resilient_call():
    """Retry with circuit breaker fallback."""
    # Retry attempts to recover
    # Circuit breaker prevents cascade
    return await external_service()
```

### Rate Limiting

```python
from cemaf.resilience import RateLimiter

# Limit API calls
api_limiter = RateLimiter(rate=10, period=1.0)  # 10 req/sec

@api_limiter.limit
async def search_external_api(query: str):
    return await api.search(query)

# Usage with multiple concurrent requests
queries = ["query1", "query2", "query3", ...]
tasks = [search_external_api(q) for q in queries]
results = await asyncio.gather(*tasks)  # Rate limited across all
```

### Anti-Pattern: Retry Without Jitter

```python
# ❌ WRONG - All requests retry at same time (thundering herd)
config = RetryConfig(
    max_attempts=3,
    initial_delay=1.0,
    exponential_base=2.0,
    jitter=False,  # Bad for coordinated systems
)

# ✅ RIGHT - Requests staggered, reduces server load
config = RetryConfig(
    max_attempts=3,
    initial_delay=1.0,
    exponential_base=2.0,
    jitter=True,  # Spread out retry attempts
)
```

---

## Integration

### With Tools (LLM Calls)

```python
from cemaf.tools import Tool
from cemaf.resilience import retry, RetryConfig

class ResilientLLMTool(Tool):
    def __init__(self, llm: LLMClient):
        self.llm = llm

    @retry(RetryConfig(max_attempts=3, initial_delay=1.0))
    async def execute(self, **kwargs) -> ToolResult:
        # LLM calls protected by retry
        result = await self.llm.complete(kwargs["messages"])
        return ToolResult(success=True, data=result.text)
```

### With RLM (Recursive Queries)

```python
from cemaf.rlm import RLMQueryTool
from cemaf.resilience import CircuitBreaker, CircuitConfig

# Protect RLM engine from cascading failures
breaker = CircuitBreaker(
    CircuitConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout=60.0,
    )
)

@breaker.protect
async def rlm_query(instruction: str, content: str):
    """RLM query with circuit breaker."""
    return await rlm_tool.execute(
        instruction=instruction,
        content=content,
    )
```

### With Orchestration (DAG Execution)

```python
from cemaf.orchestration import DAGNode
from cemaf.resilience import retry, RetryConfig

class ResilientNode(DAGNode):
    def __init__(self, name: str, func, retry_config: RetryConfig):
        self.name = name
        self.func = func
        self.retry_policy = RetryPolicy(retry_config)

    async def execute(self, inputs: dict):
        """Execute with retry."""
        return await self.retry_policy.retry_async(
            lambda: self.func(**inputs)
        )

# Use in DAG
dag = DAG()
dag.add_node(
    ResilientNode(
        name="search",
        func=search_function,
        retry_config=RetryConfig(max_attempts=3),
    )
)
```

### With Observability

```python
from cemaf.observability import Logger, Tracer

logger = Logger()
tracer = Tracer()

class ObservableRetry(RetryPolicy):
    async def retry_async(self, func, *args, **kwargs):
        attempt = 0
        while attempt < self.config.max_attempts:
            try:
                attempt += 1
                with tracer.trace(f"attempt_{attempt}"):
                    result = await func(*args, **kwargs)
                    logger.info(f"Succeeded on attempt {attempt}")
                    return result
            except Exception as e:
                logger.warning(f"Attempt {attempt} failed: {e}")
                if attempt < self.config.max_attempts:
                    await asyncio.sleep(self.calculate_delay(attempt))
                else:
                    logger.error(f"Failed after {attempt} attempts")
                    raise
```

---

## API Reference

### RetryPolicy

```python
class RetryPolicy:
    def __init__(self, config: RetryConfig):
        self.config = config

    async def retry_async(
        self,
        func: Callable,
        *args,
        **kwargs,
    ):
        """Execute function with retry logic."""
        # Implements exponential backoff with jitter
        # Raises on max_attempts exceeded

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for attempt."""
        delay = self.config.initial_delay * (
            self.config.exponential_base ** (attempt - 1)
        )
        delay = min(delay, self.config.max_delay)

        if self.config.jitter:
            delay *= random.uniform(0.5, 1.0)

        return delay
```

### CircuitBreaker

```python
class CircuitBreaker:
    def __init__(self, config: CircuitConfig):
        self.config = config
        self.state = "CLOSED"
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None

    async def protect(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.config.timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError(self.config.timeout)

        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = "CLOSED"
                    self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.config.failure_threshold:
                self.state = "OPEN"
            raise
```

### RateLimiter

```python
class RateLimiter:
    def __init__(self, rate: int, period: float):
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.last_update = time.time()

    async def acquire(self):
        """Wait until token available."""
        while self.tokens <= 0:
            await asyncio.sleep(0.01)
            self._refill()

        self.tokens -= 1

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        refill = (elapsed / self.period) * self.rate
        self.tokens = min(self.rate, self.tokens + refill)
        self.last_update = now
```

---

## Best Practices

### 1. Choose Appropriate Retry Configuration

```python
# For transient failures (network blips, rate limits)
transient_config = RetryConfig(
    max_attempts=3,
    initial_delay=0.5,
    exponential_base=2.0,
    jitter=True,
)

# For persistent services (less frequent retries)
service_config = RetryConfig(
    max_attempts=2,
    initial_delay=2.0,
    exponential_base=2.0,
    jitter=True,
)

# For critical operations (more retries, longer timeouts)
critical_config = RetryConfig(
    max_attempts=5,
    initial_delay=1.0,
    exponential_base=2.0,
    jitter=True,
)
```

### 2. Combine Patterns Wisely

```python
# ✅ Retry for transient, Circuit Breaker for cascading failures
@retry(transient_config)
@breaker.protect
async def call_external_api():
    return await api.call()

# ❌ Don't nest excessively
@retry(config1)
@retry(config2)
@breaker.protect
async def over_protected():
    # Too many retry layers, confusing
    return await something()
```

### 3. Monitor Circuit Breaker State

```python
# Track circuit state in observability
logger.info(
    "Circuit state changed",
    extra={
        "circuit": "search_api",
        "state": breaker.state,
        "failures": breaker.failure_count,
    }
)

# Alert on circuit opening
if breaker.state == "OPEN":
    alert.send("search_api circuit open", severity="warning")
```

### 4. Rate Limit Appropriately

```python
# Set rate limit based on service SLA
# LLM service: typically 1-10 requests/second
llm_limiter = RateLimiter(rate=3, period=1.0)  # 3 req/sec

# Database: depends on capacity
db_limiter = RateLimiter(rate=100, period=1.0)  # 100 req/sec

# External API: check documentation
api_limiter = RateLimiter(rate=10, period=1.0)  # 10 req/sec
```

### 5. Idempotent Operations

```python
# ✅ Retry only idempotent operations
@retry(config)
async def idempotent_read(id: str):
    """Safe to retry - same result every time."""
    return await db.get(id)

# ❌ Don't retry non-idempotent operations
async def create_resource(data: dict):
    """NOT idempotent - creates duplicate if retried."""
    return await db.create(data)

# If must retry non-idempotent: add idempotency key
async def create_resource_safe(data: dict, idempotency_key: str):
    """Safe to retry with idempotency key."""
    return await db.create_idempotent(data, idempotency_key)
```

---

## Common Patterns

### Pattern 1: Resilient Service Call

```python
async def call_external_service(query: str) -> dict:
    """Call external service with full resilience."""
    config = RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exponential_base=2.0,
        jitter=True,
    )

    retry_policy = RetryPolicy(config)
    breaker = CircuitBreaker(
        CircuitConfig(
            failure_threshold=5,
            success_threshold=2,
            timeout=60.0,
        )
    )

    try:
        return await retry_policy.retry_async(
            breaker.protect,
            lambda: service.call(query),
        )
    except CircuitBreakerOpenError:
        logger.warning("Service unavailable, using fallback")
        return get_cached_result(query)
    except Exception as e:
        logger.error(f"Service call failed: {e}")
        raise
```

### Pattern 2: Rate-Limited Batch Processing

```python
async def process_batch(items: list) -> list[dict]:
    """Process items with rate limiting."""
    limiter = RateLimiter(rate=10, period=1.0)

    async def process_item(item):
        await limiter.acquire()  # Wait for rate limit
        return await process(item)

    tasks = [process_item(item) for item in items]
    return await asyncio.gather(*tasks)
```

### Pattern 3: Cascading Failure Prevention

```python
class ResilientAgent:
    def __init__(self, name: str, llm: LLMClient):
        self.name = name
        self.llm = llm
        self.breaker = CircuitBreaker(...)
        self.retry_policy = RetryPolicy(...)

    @property
    def is_available(self) -> bool:
        """Check if agent is available."""
        return self.breaker.state != "OPEN"

    async def execute(self, task: str) -> str:
        """Execute with cascading failure protection."""
        if not self.is_available:
            return f"Agent {self.name} unavailable"

        try:
            return await self.retry_policy.retry_async(
                self.breaker.protect,
                lambda: self.llm.complete([Message(role=Role.USER, content=task)]),
            )
        except Exception as e:
            logger.error(f"Agent {self.name} failed: {e}")
            return f"Error: {e}"
```

---

## Troubleshooting

### Issue: Infinite Retry Loop

```python
# Problem: Operation never succeeds, keeps retrying
# Solution: Add max_attempts and log failures

@retry(RetryConfig(max_attempts=3, initial_delay=1.0))
async def failing_operation():
    # If this always fails, will retry 3 times then raise
    # Check logs to see why it's failing
    pass
```

### Issue: Circuit Breaker Too Sensitive

```python
# Problem: Circuit opens too quickly
# Solution: Increase failure threshold

# ❌ Opens after 1 failure
breaker = CircuitBreaker(CircuitConfig(failure_threshold=1))

# ✅ Opens after 5 failures (more tolerant)
breaker = CircuitBreaker(CircuitConfig(failure_threshold=5))
```

### Issue: Rate Limit Too Strict

```python
# Problem: Requests queuing up, latency increasing
# Solution: Increase rate or use adaptive rate limiting

# ❌ Too strict
limiter = RateLimiter(rate=1, period=1.0)  # 1 req/sec

# ✅ Better
limiter = RateLimiter(rate=10, period=1.0)  # 10 req/sec
```

---

## Configuration

```python
# config.yaml
resilience:
  retry:
    max_attempts: 3
    initial_delay: 1.0
    exponential_base: 2.0
    jitter: true

  circuit_breaker:
    failure_threshold: 5
    success_threshold: 2
    timeout: 60.0

  rate_limiter:
    llm_requests_per_second: 3
    database_requests_per_second: 100
    api_requests_per_second: 10
```

---

**Related Documentation**:
- [Observability Module](./observability.md) - Monitoring patterns
- [Tools Module](./tools.md) - Tool execution
- [LLM Module](./llm.md) - External API calls
- [Orchestration Module](./orchestration.md) - DAG execution
