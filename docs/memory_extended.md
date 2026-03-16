# Memory Module - Extended Documentation

## Overview

The memory module manages short-term and long-term memory with hierarchical scoping, enabling agents to remember facts, learn from interactions, and share knowledge across contexts.

**What it does**: Provides MemoryStore protocol for storing and retrieving memory items at different scopes (brand-level, project-level, conversation-level, turn-level). Supports TTL-based expiration, priority scoring, and scope hierarchy. Built-in InMemoryStore for testing, extensible for persistent backends.

**Key use cases**:
- Store facts learned during conversation for later reference
- Share brand knowledge across all projects and conversations
- Maintain per-user preferences and history
- Organize memory by scope to prevent inappropriate sharing
- Implement adaptive agents that learn and evolve
- Cache expensive computations with TTL

**When to use vs. alternatives**: Use memory for data that must survive across runs and conversations at different scopes. Use it for facts and knowledge the agent learns. Use cache module for pure performance optimization without semantic scoping.

## Core Concepts

### Memory Scopes

Memory is hierarchical by scope, each with different lifetime and visibility:

**BRAND**: Shared across entire system. Brand-level knowledge, policies, guidelines. Lives until explicitly deleted. All agents, projects, users can access.

**PROJECT**: Project-specific knowledge. Shared within project but not across projects. Lives until project archived. Agents in same project can access.

**AUDIENCE_SEGMENT**: Audience-specific insights. Lives for audience lifecycle. Supports A/B testing with different audience knowledge.

**PLATFORM**: Platform-specific knowledge. Twitter guidelines, LinkedIn tone, etc. Lives until platform changes. Platform-specific agents access.

**PERSONAE**: Persona-specific knowledge. Brand voice characteristics, style preferences. Lives for persona lifetime. Persona-specific agents access.

**CONVERSATION**: Conversation-scoped knowledge. Facts learned during single conversation. Cleared after conversation. Only accessible within conversation.

**TURN**: Single-turn knowledge. Temporary state within one agent action. Cleared after turn completes. Cleared immediately after action.

### Memory Item Lifecycle

```python
# Create item
item = MemoryItem(
    scope=MemoryScope.PROJECT,
    key="brand_colors",
    value={"primary": "#FF5733", "secondary": "#33FF57"},
    confidence=0.95,
    ttl_seconds=86400  # 24 hours
)

# Store
await store.set(item)

# Retrieve
retrieved = await store.get(MemoryScope.PROJECT, "brand_colors")

# Update confidence (stronger if confirmed multiple times)
await store.update_confidence("brand_colors", 0.99)

# Expires after TTL
# After 24 hours, get returns None
```

### Confidence and Priority

Each memory item has confidence (0-1) indicating certainty:
- 1.0: Verified fact, explicit instruction
- 0.8-0.99: Learned from multiple examples
- 0.5-0.79: Inferred from few examples
- 0.3-0.49: Speculation, weak evidence
- < 0.3: Uncertain, requires caution

Agents use confidence to decide whether to rely on memory:
- Use high confidence (>0.8) in decisions
- Flag medium confidence (0.5-0.8) for verification
- Ignore low confidence (<0.5) unless verified

## Usage Examples

### Brand Knowledge

```python
from cemaf.memory import InMemoryStore, MemoryItem
from cemaf.core.enums import MemoryScope

store = InMemoryStore()

# Store brand guidelines (high confidence, long TTL)
brand_voice = MemoryItem(
    scope=MemoryScope.BRAND,
    key="voice_guidelines",
    value={
        "tone": "conversational",
        "formality": "medium",
        "humor": "light",
        "jargon_level": "intermediate"
    },
    confidence=1.0,  # Explicit instruction
    ttl_seconds=365 * 24 * 3600  # 1 year
)

await store.set(brand_voice)

# All projects reference same brand knowledge
brand_voice = await store.get(MemoryScope.BRAND, "voice_guidelines")
assert brand_voice is not None
print(f"Brand tone: {brand_voice['tone']}")
```

### Learning During Conversation

```python
# During conversation, learn about user
await store.set(MemoryItem(
    scope=MemoryScope.CONVERSATION,
    key="user_preferences",
    value={
        "preferred_format": "bullet_points",
        "technical_level": "beginner",
        "language": "simple"
    },
    confidence=0.7  # Inferred from interaction
))

# Later in conversation, apply learned preference
preferences = await store.get(MemoryScope.CONVERSATION, "user_preferences")
if preferences:
    format_response(response, format=preferences["preferred_format"])
```

### Project-Specific Knowledge

```python
# During project execution, discover insights
project_facts = MemoryItem(
    scope=MemoryScope.PROJECT,
    key="audience_insights",
    value={
        "primary_demographic": "25-40 year olds",
        "platform_preference": "twitter",
        "engagement_peak_time": "9-10 AM EST",
        "tone_preference": "humorous"
    },
    confidence=0.85,
    ttl_seconds=7 * 24 * 3600  # 1 week, refresh regularly
)

await store.set(project_facts)

# Subsequent runs use learned insights
insights = await store.get(MemoryScope.PROJECT, "audience_insights")
optimal_time = insights["engagement_peak_time"]
```

### Multi-Scope Queries

```python
# Get memory considering scope hierarchy
# Priority: TURN → CONVERSATION → PERSONAE → PLATFORM → AUDIENCE_SEGMENT → PROJECT → BRAND

async def get_memory_with_hierarchy(key: str):
    """Get memory considering scope hierarchy."""
    for scope in [MemoryScope.TURN, MemoryScope.CONVERSATION, MemoryScope.PROJECT, MemoryScope.BRAND]:
        item = await store.get(scope, key)
        if item:
            return item
    return None

# Get style guide (could be at any scope level)
style = await get_memory_with_hierarchy("style_guide")
```

### Temporal Memory with TTL

```python
# Hot facts expire after period to prevent staleness
trending_topic = MemoryItem(
    scope=MemoryScope.PROJECT,
    key="trending_topic_today",
    value={"topic": "AI regulation", "sentiment": "positive"},
    confidence=0.9,
    ttl_seconds=24 * 3600  # Refresh daily
)

await store.set(trending_topic)

# After 24 hours, get returns None (expired)
tomorrow = await store.get(MemoryScope.PROJECT, "trending_topic_today")
if tomorrow is None:
    # Topic expired, refresh
    trending_topic = MemoryItem(...)
    await store.set(trending_topic)
```

### Updating Confidence Through Repetition

```python
# First observation
observation1 = MemoryItem(
    scope=MemoryScope.PROJECT,
    key="audience_likes_emojis",
    value=True,
    confidence=0.5  # Initial observation
)
await store.set(observation1)

# Second observation confirms
await store.update_confidence("audience_likes_emojis", 0.7)

# Third observation strengthens
await store.update_confidence("audience_likes_emojis", 0.85)

# High confidence, can confidently use
fact = await store.get(MemoryScope.PROJECT, "audience_likes_emojis")
if fact and fact.confidence >= 0.8:
    add_emojis_to_output()
```

### Scope-Aware Access Control

```python
# Memory enforces scope isolation
async def get_appropriate_memory(scope_context: MemoryScope):
    """Get memory appropriate for current context."""
    accessible_scopes = {
        MemoryScope.TURN: [MemoryScope.TURN, MemoryScope.CONVERSATION, MemoryScope.PROJECT, MemoryScope.BRAND],
        MemoryScope.CONVERSATION: [MemoryScope.CONVERSATION, MemoryScope.PROJECT, MemoryScope.BRAND],
        MemoryScope.PROJECT: [MemoryScope.PROJECT, MemoryScope.BRAND],
        MemoryScope.BRAND: [MemoryScope.BRAND],
    }

    # Only access scopes within hierarchy
    for scope in accessible_scopes[scope_context]:
        memory = await store.get(scope, key)
        if memory:
            return memory

    return None
```

### Common Mistake: Overwriting Learning

```python
# ❌ WRONG - Replace learned confidence with weak observation
fact = await store.get(MemoryScope.PROJECT, "audience_likes_emojis")
# fact.confidence = 0.85 (learned from many examples)

# New observation with low confidence overwrites
await store.set(MemoryItem(
    scope=MemoryScope.PROJECT,
    key="audience_likes_emojis",
    value=False,
    confidence=0.3  # One counterexample
))
# Lost strong signal from 10 examples

# ✅ CORRECT - Update confidence, don't replace
existing = await store.get(MemoryScope.PROJECT, "audience_likes_emojis")
# Consider new observation alongside existing confidence
new_confidence = (existing.confidence * 0.8 + 0.3 * 0.2)  # Weighted average
await store.update_confidence("audience_likes_emojis", new_confidence)
```

## Integration

### With Orchestration Module

```python
from cemaf.memory import InMemoryStore, MemoryScope

class AgentWithMemory:
    """Agent that uses memory for reasoning."""

    def __init__(self, store):
        self.memory = store

    async def act(self, task):
        # Get relevant memory
        brand_voice = await self.memory.get(MemoryScope.BRAND, "voice_guidelines")
        project_facts = await self.memory.get(MemoryScope.PROJECT, "audience_insights")
        conversation_context = await self.memory.get(MemoryScope.CONVERSATION, "user_preferences")

        # Use memory in reasoning
        prompt = f"""
        Brand voice: {brand_voice}
        Audience: {project_facts}
        User preferences: {conversation_context}

        Task: {task}
        """

        response = await self.llm.generate(prompt)

        # Learn from outcome
        await self.memory.set(MemoryItem(
            scope=MemoryScope.CONVERSATION,
            key="last_response_quality",
            value=response_quality_score,
            confidence=0.8
        ))

        return response
```

### With Context Module

```python
from cemaf.context.context import Context
from cemaf.memory import MemoryScope

# Memory sources for context injection
class MemoryContextSource:
    async def get_context_for_scope(self, scope: MemoryScope):
        """Retrieve memory items as context sources."""
        memory_items = await self.store.list_by_scope(scope)

        sources = []
        for item in memory_items:
            if item.confidence >= 0.8:  # Only high-confidence
                sources.append({
                    "id": f"memory_{item.key}",
                    "content": str(item.value),
                    "confidence": item.confidence,
                    "source": f"memory:{scope.value}"
                })

        return sources
```

### With Persistence Module

```python
from cemaf.persistence.entities import Run

# Store learned facts in run outputs
run = Run(
    project_id=project.id,
    pipeline="learning_run",
    inputs={...},
    outputs={
        "learned_facts": [
            {"key": "audience_preference", "value": "emojis", "confidence": 0.85},
            {"key": "optimal_time", "value": "9am", "confidence": 0.75}
        ]
    }
)

await run_store.create(run)

# Later, load learned facts into memory
async def restore_learned_facts(run):
    if "learned_facts" in run.outputs:
        for fact in run.outputs["learned_facts"]:
            await memory.set(MemoryItem(
                scope=MemoryScope.PROJECT,
                key=fact["key"],
                value=fact["value"],
                confidence=fact["confidence"]
            ))
```

## API Reference

### MemoryItem Dataclass

```python
@dataclass
class MemoryItem:
    scope: MemoryScope              # Which scope this belongs to
    key: str                        # Unique key within scope
    value: Any                      # Stored value
    confidence: float = 0.5         # Certainty (0-1)
    ttl_seconds: int | None = None # Time-to-live
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: JSON = Field(default_factory=dict)
```

### MemoryScope Enum

```python
class MemoryScope(str, Enum):
    BRAND = "brand"
    PROJECT = "project"
    AUDIENCE_SEGMENT = "audience_segment"
    PLATFORM = "platform"
    PERSONAE = "personae"
    CONVERSATION = "conversation"
    TURN = "turn"
```

### MemoryStore Protocol

```python
@runtime_checkable
class MemoryStore(Protocol):
    async def get(
        self,
        scope: MemoryScope,
        key: str
    ) -> MemoryItem | None: ...

    async def set(self, item: MemoryItem) -> None: ...

    async def update_confidence(
        self,
        key: str,
        new_confidence: float
    ) -> None: ...

    async def delete(self, scope: MemoryScope, key: str) -> bool: ...

    async def list_by_scope(
        self,
        scope: MemoryScope,
        min_confidence: float = 0.0
    ) -> list[MemoryItem]: ...

    async def clear_scope(self, scope: MemoryScope) -> int: ...
```

## Best Practices

### Confidence Management

- Start new observations at 0.5-0.6 (uncertain)
- Increment confidence when observations repeat (0.1-0.2 per confirmation)
- Cap updates to avoid overconfidence in small samples
- Decay confidence over time for temporal facts

### TTL Strategy

```python
# Facts with different shelf lives
FACT_TTLS = {
    "brand_voice": 365 * 24 * 3600,        # Annual refresh
    "audience_insights": 30 * 24 * 3600,   # Monthly refresh
    "trending_topic": 24 * 3600,           # Daily refresh
    "conversation_fact": 1 * 3600,         # Hour for session
    "turn_cache": 60,                      # Minute for action
}
```

### Common Pitfalls

**Scope violation**: Don't access inappropriate scopes. Respect hierarchy.

**Expired facts**: Always check TTL. Stale memory is worse than no memory.

**Overconfidence**: Don't assume high confidence after few examples. Use statistical updates.

**Memory bloat**: Periodically clean low-confidence or expired items.

**No versioning**: If memory changes dramatically, version it or the agent gets confused.

### When NOT to Use

- **Purely temporary state**: Use function parameters or local variables
- **Performance caching**: Use cache module instead
- **Sensitive data**: Don't store PII or secrets in memory
- **High-frequency updates**: Memory is for relatively stable facts, not state machines

### Scope Hierarchy Example

```python
# When generating social content:
# 1. Check TURN memory (this action's context)
# 2. Check CONVERSATION memory (this user's preferences)
# 3. Check PLATFORM memory (Twitter guidelines)
# 4. Check PERSONAE memory (brand persona)
# 5. Check PROJECT memory (audience insights)
# 6. Check BRAND memory (brand guidelines)

final_style = {}
for scope in [TURN, CONVERSATION, PLATFORM, PERSONAE, PROJECT, BRAND]:
    style_fact = await memory.get(scope, "content_style")
    if style_fact and style_fact.confidence >= 0.7:
        final_style.update(style_fact.value)
```

## Deduplication

The deduplication system prevents near-duplicate memory items from accumulating. It uses a two-stage detection strategy: exact key match first, then semantic similarity via embeddings.

**Source**: `memory/deduplication.py`

### Protocol

```python
@runtime_checkable
class MemoryDeduplicator(Protocol):
    async def find_duplicates(
        self, candidate: MemoryItem, *, threshold: float = 0.85,
    ) -> tuple[DuplicateMatch, ...]: ...

    async def resolve(
        self, candidate: MemoryItem, matches: tuple[DuplicateMatch, ...],
    ) -> DeduplicationResult: ...
```

### Match Types

| MatchType | Description | Similarity |
|-----------|-------------|------------|
| `EXACT_KEY` | Same scope + key | 1.0 |
| `SEMANTIC` | Embedding similarity above threshold | >= threshold |
| `PARTIAL_KEY` | Reserved for substring key matching | varies |

### Resolution Actions

| Action | When | Behavior |
|--------|------|----------|
| `STORE_NEW` | No matches found | Store candidate as-is |
| `SKIP` | Semantic match with higher-confidence existing item | Do not store |
| `MERGE` | Exact key or semantic match where candidate has higher confidence | Keep best confidence, return merged item |

### SemanticDeduplicator

The default implementation. On `find_duplicates`, it first checks for an exact key match via `SemanticMemoryStore.get()`. If found, returns immediately with similarity 1.0. Otherwise, embeds the candidate (`key: json(value)`) and searches the same scope for similar items.

On `resolve`, it picks the best match. For exact keys, it merges (keeping the higher-confidence value). For semantic matches, it skips if the existing item has higher confidence, otherwise merges.

```python
from cemaf.memory.deduplication import SemanticDeduplicator

dedup = SemanticDeduplicator(
    semantic_store=semantic_store,
    similarity_threshold=0.85,
)

matches = await dedup.find_duplicates(candidate=new_item)
result = await dedup.resolve(candidate=new_item, matches=matches)

if not result.skipped:
    await manager.remember(scope=result.item.scope, key=result.item.key, value=result.item.value)
```

## Three-Tier Progressive Loading

Memory items are represented at three resolution tiers (L0/L1/L2) to enable progressive context loading under token budgets.

**Source**: `memory/tiered.py`, `memory/tiered_store.py`

### Loading Tiers

| Tier | Token Budget | Content | Use Case |
|------|-------------|---------|----------|
| L0 | ~100 tokens | One-sentence abstract (key + first sentence) | Broad scan, metadata filtering |
| L1 | ~2K tokens | Overview (truncated full content) | Planning, shortlisting |
| L2 | Full | Complete content | Final selection, execution |

### TieredMemoryItem

Pre-computes all three representations at store time:

```python
@dataclass(frozen=True)
class TieredMemoryItem:
    item: MemoryItem
    l0_abstract: str
    l0_token_count: int
    l1_overview: str
    l1_token_count: int
    l2_token_count: int

    def content_at_tier(self, tier: LoadingTier) -> str: ...
    def to_compacted(self, tier: LoadingTier) -> CompactedMemory: ...
```

### TieredMemoryStore

Wraps `SemanticMemoryStore` with tier-aware progressive retrieval:

```python
from cemaf.memory.factories import create_tiered_store

tiered = create_tiered_store()

# Store with tier generation
tiered_item = await tiered.store_with_tiers(item=memory_item)

# Progressive search: L0 broad scan (50) -> L1 shortlist (10) -> L2 final (5)
results = await tiered.progressive_search(
    query=MemoryQuery(text="user preferences", scope=MemoryScope.PROJECT),
    l0_limit=50,
    l1_limit=10,
    l2_limit=5,
)
```

### TruncationTierGenerator

Default tier generator that uses truncation heuristics (no LLM required):
- L0: `key: first_sentence`, max 400 chars
- L1: Truncated to 8000 chars
- L2: Full JSON content

## Scope Propagation

Hierarchical scope paths enable parent-to-child score propagation during memory retrieval. A query for `project/campaign` can inherit relevance from `project`.

**Source**: `memory/scope_hierarchy.py`

### ScopePath

```python
from cemaf.memory.scope_hierarchy import ScopePath

path = ScopePath.from_string("project/campaign/assets")
assert path.root == "project"
assert path.depth == 3
assert str(path.parent) == "project/campaign"
assert path.is_ancestor_of(ScopePath.from_string("project/campaign/assets/images"))
```

### PropagatingScorer

Scores scope paths against a query, then propagates parent scores down to children with a decay factor:

```python
from cemaf.memory.factories import create_scope_scorer

scorer = create_scope_scorer(
    semantic_store=semantic_store,
    propagation_factor=0.7,  # child += parent_score * 0.7
)

nodes = await scorer.score_scopes(
    query=MemoryQuery(text="brand colors", scope=MemoryScope.PROJECT),
    scope_paths=(
        ScopePath.from_string("project"),
        ScopePath.from_string("project/design"),
        ScopePath.from_string("project/design/colors"),
    ),
)
# nodes sorted by score descending; deeper paths inherit parent relevance
```

The algorithm:
1. Sample up to 5 items per scope path via semantic search
2. Compute base score as mean `combined_score` of sampled results
3. Sort paths by depth, propagate: `child_score += parent_score * propagation_factor`
4. Return `ScopeNode` tuples sorted by score descending

## Post-Session Extraction

Automatically promotes short-lived session memories to long-term storage when a session ends. Runs inside `SessionManager.dispose()`.

**Source**: `memory/extraction.py`, `memory/extraction_pipeline.py`

### MemoryExtractor Protocol

```python
@runtime_checkable
class MemoryExtractor(Protocol):
    async def extract(
        self,
        *,
        session_memories: tuple[MemoryItem, ...],
        episodes: tuple[Episode, ...],
        recent_events: tuple[EpisodicEvent, ...],
    ) -> tuple[ExtractedMemory, ...]: ...
```

### RuleBasedExtractor

Default heuristic extractor (no LLM required). Applies three rules:

| Rule | Input | Output | Target Scope |
|------|-------|--------|-------------|
| High-confidence promotion | SESSION items with confidence >= 0.6 | FACT | PROJECT |
| Pattern detection | Same action repeated 3+ times | PATTERN | PROJECT |
| Correction extraction | Error/correction events with importance >= 0.7 | CORRECTION | PROJECT |

### ExtractionPipeline

Full pipeline: extract -> deduplicate -> store -> emit event.

```python
from cemaf.memory.factories import create_extraction_pipeline

pipeline = create_extraction_pipeline(
    memory_manager=manager,
    deduplicator=deduplicator,  # optional, skips dedup if None
    event_bus=event_bus,        # optional, emits MEMORY_EXTRACTED event
)

report = await pipeline.run(
    session_memories=session_items,
    episodes=episodes,
    recent_events=recent_events,
)

# report.extracted_count, report.stored_count, report.deduplicated_count, report.skipped_count
```

The pipeline emits a `MEMORY_EXTRACTED` event with a payload containing item details for downstream subscribers.

## SQLite Store

Persistent `MemoryStore` implementation backed by SQLite via `aiosqlite`. Suitable for single-node production deployments.

**Source**: `memory/sqlite_store.py`

### Schema

```sql
CREATE TABLE IF NOT EXISTS memory_items (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ttl_seconds REAL,
    expires_at TEXT,
    scope_path TEXT,
    PRIMARY KEY (scope, key)
)
```

### Usage

```python
from cemaf.memory.sqlite_store import SqliteMemoryStore

store = SqliteMemoryStore(db_path="cemaf_memory.db")

await store.set(item=memory_item)
item = await store.get(scope=MemoryScope.PROJECT, key="brand_colors")
items = await store.list_by_scope(scope=MemoryScope.PROJECT)
removed = await store.cleanup_expired()  # returns count of removed items
```

Key behaviors:
- Auto-creates table on first operation (`_ensure_table`)
- `get()` checks expiration and auto-deletes expired items
- `list_by_scope()` filters expired items in the SQL query
- `cleanup_expired()` batch-removes all expired rows
- Uses `INSERT OR REPLACE` for upsert semantics

### Factory

```python
from cemaf.memory.factories import create_memory_store

# In-memory (default, for testing)
store = create_memory_store(backend="memory")

# SQLite (for production)
store = create_memory_store(backend="sqlite")
# Reads CEMAF_MEMORY_SQLITE_PATH env var, defaults to "cemaf_memory.db"
```

## Factory Functions

All memory factories live in `memory/factories.py`. They wire internal dependencies with sensible defaults while accepting injectable overrides.

| Factory | Creates | Key Deps |
|---------|---------|----------|
| `create_memory_store(backend=)` | `InMemoryStore` or `SqliteMemoryStore` | None |
| `create_memory_manager(memory_store=, embedding_provider=, vector_store=, deduplicator=)` | `DefaultMemoryManager` | MemoryStore, VectorStore, EmbeddingProvider |
| `create_session_manager(memory_manager=, extraction_pipeline=)` | `DefaultSessionManager` | MemoryManager, compactor |
| `create_tiered_store(memory_store=)` | `TieredMemoryStore` | SemanticMemoryStore, TruncationTierGenerator |
| `create_extraction_pipeline(memory_manager=, extractor=, deduplicator=, event_bus=)` | `ExtractionPipeline` | MemoryManager, MemoryExtractor |
| `create_scope_scorer(semantic_store=, propagation_factor=)` | `PropagatingScorer` | SemanticMemoryStore |
