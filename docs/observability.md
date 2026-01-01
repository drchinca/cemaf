# Observability

Logging, tracing, and metrics for monitoring.

## Observability Architecture

```mermaid
flowchart TB
    subgraph Components
        LOGGER[Logger<br/>Structured logs]
        TRACER[Tracer<br/>Distributed tracing]
        METRICS[Metrics<br/>Measurements]
        RUNLOG[RunLogger<br/>Run recording]
    end

    subgraph Outputs
        CONSOLE[Console<br/>Development]
        FILE[File<br/>Persistence]
        REMOTE[Remote<br/>APM systems]
    end

    subgraph Run Recording
        CALLS[Tool Calls]
        LLMCALLS[LLM Calls]
        PATCHES[Context Patches]
        RECORD[RunRecord]
    end

    LOGGER --> CONSOLE
    LOGGER --> FILE
    TRACER --> REMOTE
    METRICS --> REMOTE
    RUNLOG --> CALLS
    RUNLOG --> LLMCALLS
    RUNLOG --> PATCHES
    CALLS --> RECORD
    LLMCALLS --> RECORD
    PATCHES --> RECORD
```

## Run Recording Flow

```mermaid
sequenceDiagram
    participant Executor
    participant RunLogger
    participant Tool
    participant Record as RunRecord

    Executor->>RunLogger: start_run(run_id, dag_name)

    loop For each node
        Executor->>Tool: execute()
        Tool-->>Executor: Result
        Executor->>RunLogger: record_tool_call(call)
        Executor->>RunLogger: record_patch(patch)
    end

    Executor->>RunLogger: end_run(context, success)
    RunLogger-->>Executor: RunRecord
    Note over Record: Serializable for replay
```

## Logger

```python
from cemaf.observability.simple import SimpleLogger

logger = SimpleLogger()
logger.info("Operation started")
logger.error("Operation failed", exc_info=True)
```
