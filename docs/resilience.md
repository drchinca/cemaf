# Resilience

Retry, circuit breaker, and rate limiting for robust operations.

## Resilience Architecture

```mermaid
flowchart TB
    subgraph Patterns
        RETRY[RetryPolicy<br/>Automatic retries]
        CB[CircuitBreaker<br/>Fail fast]
        RL[RateLimiter<br/>Throttling]
    end

    subgraph States
        CLOSED[Closed<br/>Normal operation]
        OPEN[Open<br/>Fail immediately]
        HALF[Half-Open<br/>Testing recovery]
    end

    subgraph Backoff
        CONST[Constant<br/>Fixed delay]
        EXP[Exponential<br/>2^n delay]
        JITTER[Jitter<br/>Random variance]
    end

    RETRY --> CONST
    RETRY --> EXP
    RETRY --> JITTER
    CB --> CLOSED
    CLOSED -->|failures| OPEN
    OPEN -->|timeout| HALF
    HALF -->|success| CLOSED
    HALF -->|failure| OPEN
```

## Circuit Breaker Flow

```mermaid
sequenceDiagram
    participant Caller
    participant CB as CircuitBreaker
    participant Service

    Note over CB: State: CLOSED
    Caller->>CB: execute(fn)
    CB->>Service: Call
    Service-->>CB: Success
    CB-->>Caller: Result

    Note over CB: Multiple failures...
    Caller->>CB: execute(fn)
    CB->>Service: Call
    Service-->>CB: Failure (5th)
    Note over CB: State: OPEN
    CB-->>Caller: CircuitOpenError

    Note over CB: After timeout...
    Note over CB: State: HALF-OPEN
    Caller->>CB: execute(fn)
    CB->>Service: Test call
    Service-->>CB: Success
    Note over CB: State: CLOSED
    CB-->>Caller: Result
```

## Retry Policy

```python
from cemaf.resilience.retry import RetryPolicy

policy = RetryPolicy(
    max_attempts=3,
    backoff_type="exponential",
    initial_delay=1.0
)

result = await policy.execute(async_function)
```

## Circuit Breaker

```python
from cemaf.resilience.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker(
    failure_threshold=5,
    timeout_seconds=60
)

result = await breaker.execute(async_function)
```

## Rate Limiter

```python
from cemaf.resilience.rate_limiter import RateLimiter

limiter = RateLimiter(max_calls=10, time_window=60)

result = await limiter.execute(async_function)
```
