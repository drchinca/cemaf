# Persistence

Entities for tracking projects, runs, and artifacts.

## Persistence Architecture

```mermaid
flowchart TB
    subgraph Entities
        PROJ[Project<br/>Top-level container]
        RUN[Run<br/>Execution instance]
        ART[ContextArtifact<br/>Versioned content]
    end

    subgraph Relationships
        PROJ -->|has many| RUN
        PROJ -->|has many| ART
        RUN -->|produces| ART
    end

    subgraph Status
        ACTIVE[active]
        RUNNING[running]
        COMPLETED[completed]
        FAILED[failed]
    end

    PROJ --> ACTIVE
    RUN --> RUNNING
    RUN --> COMPLETED
    RUN --> FAILED
```

## Entity Lifecycle

```mermaid
sequenceDiagram
    participant User
    participant Project
    participant Run
    participant Artifact

    User->>Project: create(name)
    Note over Project: status: active

    User->>Run: create(project_id)
    Note over Run: status: running

    Run->>Artifact: create(content)
    Note over Artifact: version: 1

    Run->>Artifact: update(content)
    Note over Artifact: version: 2

    Run->>Run: complete()
    Note over Run: status: completed
```

## Entities

```python
from cemaf.persistence.entities import Project, Run, ContextArtifact

# Project
project = Project(id="proj1", name="My Project", status="active")

# Run
run = Run(id="run1", project_id="proj1", status=RunStatus.RUNNING)

# Artifact
artifact = ContextArtifact(
    id="art1",
    project_id="proj1",
    content="artifact content",
    version=1
)
```
