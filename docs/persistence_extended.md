# Persistence Module - Extended Documentation

## Overview

The persistence module provides a complete data layer for CEMAF applications, managing projects, content items, execution runs, and context artifacts with immutable, versioned entities.

**What it does**: Defines core domain entities (Project, Run, ContextArtifact, ContentItem) and pluggable storage protocols that enable multiple backend implementations without changing application code. All entities are frozen Pydantic models with builder methods for safe state transitions.

**Key use cases**:
- Multi-tenant project management with scoped access
- Content production workflows with status tracking
- Pipeline execution recording and audit trails
- Context artifact versioning with git-like semantics
- Publishing workflows with scheduling and approval gates

**When to use vs. alternatives**: Use persistence when you need structured, queryable data storage with type safety. Use it for any application requiring audit trails, multi-tenancy, or complex state transitions. Don't use for unstructured logs (use observability module) or real-time event streams (use events module).

## Core Concepts

### Entities Architecture

The module centers on four core entities with clear responsibilities:

**Project**: Container for all workflow data, with immutable snapshots of state. Projects transition through statuses (DRAFT → ACTIVE → PAUSED/COMPLETED → ARCHIVED). Use `project.with_status()` for safe state changes.

**Run**: Execution record capturing pipeline metadata, inputs, outputs, and performance metrics. Runs are created when a pipeline executes and updated with completion details. Store JSON inputs/outputs for full reproducibility, tokens_used and cost_usd for billing.

**ContextArtifact**: Versioned context documents with git-like semantics. Each artifact type (BRIEF, CONTENT_CALENDAR, SCRIPTS, etc.) maintains version history. Use `artifact.with_new_version()` to create immutable snapshots. SHA enables deduplication.

**ContentItem**: Publishable content items with multi-stage workflow. Items move through DRAFT → PENDING_REVIEW → APPROVED → SCHEDULED → PUBLISHED. Includes platform, format, and asset metadata for omnichannel publishing.

### Design Philosophy

**Immutability**: All entities are frozen Pydantic models. State transitions create new instances with updated fields rather than mutating existing objects. This prevents accidental state corruption and enables proper audit trails.

**Protocol-based storage**: Actual storage is abstracted behind protocols (ProjectStore, RunStore, ArtifactStore, ContentStore). This allows testing with InMemoryStore, development with FileStore, and production with PostgresStore without code changes.

**Type safety**: Strong typing with enums for statuses, ID wrapper types for validation, and JSON fields for flexible metadata. Pydantic's validation catches malformed data at boundaries.

**Versioning and reproducibility**: Runs capture complete inputs/outputs. Artifacts maintain version history. This enables replay, debugging, and understanding what happened at any point in time.

### Key Abstractions

```python
# Status enums enforce valid transitions
class ProjectStatus(str, Enum):
    DRAFT, ACTIVE, PAUSED, COMPLETED, ARCHIVED

# ID types provide type safety
type ProjectID = NewType('ProjectID', str)
type RunID = NewType('RunID', str)

# Immutable factories for safe creation
project = Project(name="Campaign Q1", owner_id="user1")
project_v2 = project.with_status(ProjectStatus.ACTIVE)

# Full JSON capture for reproducibility
run = Run(project_id=p.id, inputs={"brief": "..."}, outputs={...})
```

## Usage Examples

### Basic Project and Run Management

```python
from cemaf.persistence.entities import Project, Run, ProjectStatus, RunStatus
from cemaf.core.types import ProjectID
from datetime import datetime

# Create a project
project = Project(
    name="Social Media Campaign Q1",
    description="Multi-platform content creation",
    tenant_id="acme-corp"
)

# Projects start as DRAFT
assert project.status == ProjectStatus.DRAFT

# Activate when ready
active_project = project.with_status(ProjectStatus.ACTIVE)

# Create a run for pipeline execution
run = Run(
    project_id=project.id,
    pipeline="content_generation",
    dag_name="multi_platform_gen",
    inputs={
        "brief": "Create Q1 social content",
        "platforms": ["twitter", "linkedin", "tiktok"],
        "tone": "professional"
    }
)

# Simulate pipeline execution
updated_run = run.with_completion(
    status=RunStatus.COMPLETED,
    outputs={
        "twitter_posts": 5,
        "linkedin_articles": 2,
        "tiktok_videos": 3,
        "total_generated": 10
    }
)

# Access metadata
print(f"Pipeline ran for {updated_run.duration_seconds} seconds")
print(f"Cost: ${updated_run.total_cost_usd}")
```

### Context Artifact Versioning

```python
from cemaf.persistence.entities import ContextArtifact
from cemaf.core.enums import ContextArtifactType
import hashlib

# Create initial artifact
brief_v1 = ContextArtifact(
    project_id=project.id,
    type=ContextArtifactType.BRIEF,
    content="Initial campaign brief...",
    source="user_input",
    sha=hashlib.sha256(b"Initial campaign brief...").hexdigest()
)

# Update with new content creates immutable snapshot
updated_brief = brief_v1.with_new_version(
    content="Updated brief with new insights...",
    sha=hashlib.sha256(b"Updated brief with new insights...").hexdigest()
)

assert updated_brief.version == 2
assert updated_brief.id != brief_v1.id  # New entity, not mutation
assert brief_v1.id  # Original preserved for history
```

### Content Item Publishing Workflow

```python
from cemaf.persistence.entities import ContentItem, ContentStatus

# Create draft from run output
post = ContentItem(
    project_id=project.id,
    platform="twitter",
    format="tweet",
    brief="Q1 Launch Announcement",
    title="",
    body="We're excited to announce our Q1 initiative...",
    hashtags=("Q1Launch", "Innovation", "Growth")
)

# Workflow: DRAFT → PENDING_REVIEW
pending_post = post.with_status(ContentStatus.PENDING_REVIEW)

# → APPROVED
approved_post = pending_post.with_status(ContentStatus.APPROVED)

# → SCHEDULED with timing
scheduled_post = approved_post.model_copy(
    update={
        "status": ContentStatus.SCHEDULED,
        "scheduled_at": datetime(2025, 1, 30, 9, 0)
    }
)

# → PUBLISHED when time comes
published_post = scheduled_post.with_status(ContentStatus.PUBLISHED).model_copy(
    update={"published_at": utc_now()}
)
```

### Advanced: Working with Multiple Artifacts

```python
from cemaf.persistence.entities import Run, ContextArtifact
from cemaf.core.enums import ContextArtifactType

# Run with multiple artifact outputs
run = Run(
    project_id=project.id,
    pipeline="full_campaign",
    inputs={"duration_weeks": 4, "budget": 50000}
)

# Create and track multiple artifacts
artifacts = {
    "brief": ContextArtifact(
        project_id=project.id,
        type=ContextArtifactType.BRIEF,
        content="Campaign Brief..."
    ),
    "calendar": ContextArtifact(
        project_id=project.id,
        type=ContextArtifactType.CONTENT_CALENDAR,
        content="Week 1: 5 posts, Week 2: 8 posts..."
    ),
    "scripts": ContextArtifact(
        project_id=project.id,
        type=ContextArtifactType.SCRIPTS,
        content="Video scripts with timings..."
    )
}

# Complete run with all artifacts
completed_run = run.with_completion(
    status=RunStatus.COMPLETED,
    outputs={
        "artifact_ids": [a.id for a in artifacts.values()],
        "artifacts_created": len(artifacts)
    }
)
```

### Common Mistake: Mutating Entities

```python
# ❌ WRONG - Don't modify frozen models
run.status = RunStatus.COMPLETED  # TypeError: frozen

# ❌ WRONG - Don't lose original state
original = project
original = original.with_status(ProjectStatus.ACTIVE)
# Now you lost the DRAFT version

# ✅ CORRECT - Use builder methods
completed_run = run.with_completion(
    status=RunStatus.COMPLETED,
    outputs={...}
)

# ✅ CORRECT - Keep history
draft_project = project
active_project = draft_project.with_status(ProjectStatus.ACTIVE)
# Both versions accessible
```

## Integration

### With Storage Layer

The persistence module uses pluggable storage protocols. Applications provide implementations:

```python
from cemaf.persistence.protocols import ProjectStore, RunStore
from cemaf.persistence.entities import Project, ProjectStatus

# Your implementation
class PostgresProjectStore:
    async def create(self, project: Project) -> Project:
        # Insert into database
        return project

    async def get(self, project_id: ProjectID) -> Project | None:
        # Query database
        return project

    async def list_by_status(self, status: ProjectStatus | None = None) -> tuple[Project, ...]:
        # Query by status
        return (project1, project2)

# Use in orchestration
store = PostgresProjectStore()
project = await store.create(project)
```

### With Observability Module

Runs integrate with the observability module for detailed execution tracking:

```python
from cemaf.observability.run_logger import RunLogger
from cemaf.persistence.entities import Run, RunStatus

logger = RunLogger()
run = Run(project_id=project.id, pipeline="content_gen")

# Log execution details
await logger.log_tool_call(run.id, tool="web_search", args={"q": "..."})
await logger.log_context_update(run.id, ...)

# Retrieve logs for debugging
record = await logger.get_record(run.id)
```

### With Validation Module

Use validation to enforce business rules on state transitions:

```python
from cemaf.validation import ValidationPipeline

validator = ValidationPipeline([
    RequiredFieldsRule(["platform", "format", "body"]),
    LengthRule("body", min_length=10, max_length=280),
])

# Validate before state transition
result = await validator.validate(content_item)
if result.valid:
    published = content_item.with_status(ContentStatus.PUBLISHED)
```

### With Moderation Module

Gate transitions with content safety checks:

```python
from cemaf.moderation import ModerationPipeline

moderator = ModerationPipeline([...])
result = await moderator.moderate(content_item.body)

if result.safe:
    approved = content_item.with_status(ContentStatus.APPROVED)
else:
    flagged = content_item.with_status(ContentStatus.FAILED)
```

## API Reference

### Project

```python
class Project(BaseModel):
    id: ProjectID  # Auto-generated
    name: str
    description: str = ""
    status: ProjectStatus = DRAFT
    created_at: datetime  # Auto-generated
    start_at: datetime | None = None
    end_at: datetime | None = None
    tenant_id: str | None = None  # For multi-tenancy
    owner_id: str | None = None
    metadata: JSON = {}  # Custom fields

    def with_status(self, status: ProjectStatus) -> Project
```

### Run

```python
class Run(BaseModel):
    id: RunID  # Auto-generated
    project_id: ProjectID
    pipeline: str  # Pipeline name
    dag_name: str  # DAG name
    inputs: JSON  # Full input capture
    outputs: JSON = {}
    status: RunStatus = PENDING
    error: str | None = None
    started_at: datetime  # Auto-generated
    completed_at: datetime | None = None
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    metadata: JSON = {}

    @property
    def duration_seconds(self) -> float | None

    def with_completion(
        self,
        status: RunStatus,
        outputs: JSON,
        error: str | None = None
    ) -> Run
```

### ContextArtifact

```python
class ContextArtifact(BaseModel):
    id: str  # Auto-generated per version
    project_id: ProjectID
    type: ContextArtifactType  # BRIEF, CALENDAR, etc.
    content: str
    version: int = 1
    sha: str  # For deduplication
    source: str  # Where it came from
    source_url: str | None = None
    created_at: datetime  # Auto-generated
    metadata: JSON = {}

    def with_new_version(self, content: str, sha: str) -> ContextArtifact
```

### ContentItem

```python
class ContentItem(BaseModel):
    id: str  # Auto-generated
    project_id: ProjectID
    platform: str  # twitter, linkedin, etc.
    format: str  # tweet, article, video, etc.
    brief: str
    title: str = ""
    body: str = ""
    caption: str = ""
    hashtags: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()  # Media IDs
    status: ContentStatus = DRAFT
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    run_id: RunID | None = None  # Which run created this
    metadata: JSON = {}

    def with_status(self, status: ContentStatus) -> ContentItem
```

### Storage Protocols

```python
@runtime_checkable
class ProjectStore(Protocol):
    async def create(self, project: Project) -> Project
    async def get(self, project_id: ProjectID) -> Project | None
    async def update(self, project: Project) -> Project
    async def delete(self, project_id: ProjectID) -> bool
    async def list_by_status(
        self,
        status: ProjectStatus | None = None,
        limit: int = 100
    ) -> tuple[Project, ...]

@runtime_checkable
class RunStore(Protocol):
    async def create(self, run: Run) -> Run
    async def get(self, run_id: RunID) -> Run | None
    async def update(self, run: Run) -> Run
    async def list_by_project(
        self,
        project_id: ProjectID,
        status: RunStatus | None = None,
        limit: int = 100
    ) -> tuple[Run, ...]
    async def get_latest(self, project_id: ProjectID) -> Run | None

@runtime_checkable
class ArtifactStore(Protocol):
    async def create(self, artifact: ContextArtifact) -> ContextArtifact
    async def get(self, artifact_id: str) -> ContextArtifact | None
    async def get_latest(
        self,
        project_id: ProjectID,
        artifact_type: ContextArtifactType
    ) -> ContextArtifact | None
    async def list_versions(
        self,
        project_id: ProjectID,
        artifact_type: ContextArtifactType
    ) -> tuple[ContextArtifact, ...]

@runtime_checkable
class ContentStore(Protocol):
    async def create(self, content: ContentItem) -> ContentItem
    async def get(self, content_id: str) -> ContentItem | None
    async def update(self, content: ContentItem) -> ContentItem
    async def list_by_project(
        self,
        project_id: ProjectID,
        status: ContentStatus | None = None,
        platform: str | None = None,
        limit: int = 100
    ) -> tuple[ContentItem, ...]
    async def list_scheduled(self, limit: int = 100) -> tuple[ContentItem, ...]
```

## Best Practices

### Performance Tips

- **Batch operations**: When creating multiple artifacts, collect them and insert in batches for better database performance
- **Index on status**: Index status fields for fast filtering by DRAFT, SCHEDULED, etc.
- **Archive old runs**: Periodically archive completed runs to keep queries fast
- **JSON field limits**: Store structured data in metadata JSON, but keep the main content field clean
- **SHAs for deduplication**: Always compute SHA256 of artifact content to detect duplicates

### Common Pitfalls

**Forgetting immutability**: Entities are frozen. Always use builder methods like `with_status()` not direct assignment.

**Losing state history**: Don't replace old variables with updated versions if you need to track changes. Keep references to both.

**Incomplete run metadata**: Always capture complete inputs/outputs for reproducibility. Leave nothing to memory.

**Status transition confusion**: Follow the state machine. Not all transitions are valid. Document which statuses can transition to which.

**Metadata overflow**: Don't put large data in metadata JSON. Use separate artifact entities instead. Metadata is for tags, labels, and config.

### When NOT to Use

- **Temporary data**: Don't store session state or real-time computations in persistence. Use memory module instead.
- **Raw logs**: Don't use persistence for low-level operation logs. Use observability/logging.
- **Fast-changing state**: If data changes every millisecond, persistence is too slow. Use cache or memory.
- **Ephemeral events**: Don't persist one-off events. Use events module for pub/sub patterns.

### Transactions and Consistency

All entity builders are atomic at the Python level. For database transactions:

```python
# If using PostgreSQL:
async with transaction:
    project = await store.create(project)
    run = await store.create(Run(project_id=project.id, ...))
    # Both succeed or both fail
```

### Status Machine Validation

Define and document valid transitions:

```
Project: DRAFT → ACTIVE → (PAUSED ↔ ACTIVE) → COMPLETED → ARCHIVED
Run: PENDING → RUNNING → (COMPLETED | FAILED)
ContentItem: DRAFT → PENDING_REVIEW → APPROVED → SCHEDULED → PUBLISHED
             Any status → FAILED (moderation failure)
```

Enforce in application logic:

```python
def can_publish(item: ContentItem) -> bool:
    return item.status == ContentStatus.APPROVED
```
