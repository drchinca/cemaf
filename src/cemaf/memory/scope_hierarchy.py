"""Hierarchical scope propagation for memory retrieval."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cemaf.memory.semantic import MemoryQuery, SemanticMemoryStore


@dataclass(frozen=True)
class ScopePath:
    """Hierarchical scope path like 'project/campaign/assets'."""

    segments: tuple[str, ...]

    @classmethod
    def from_string(cls, path: str) -> ScopePath:
        """Parse a slash-separated path string."""
        parts = tuple(s.strip() for s in path.split("/") if s.strip())
        if not parts:
            raise ValueError(f"Empty scope path: {path!r}")
        return cls(segments=parts)

    @property
    def root(self) -> str:
        """First segment."""
        return self.segments[0]

    @property
    def parent(self) -> ScopePath | None:
        """Parent path, or None if root-level."""
        if len(self.segments) <= 1:
            return None
        return ScopePath(segments=self.segments[:-1])

    @property
    def depth(self) -> int:
        """Number of segments."""
        return len(self.segments)

    def is_ancestor_of(self, other: ScopePath) -> bool:
        """Check if this path is an ancestor of another."""
        if self.depth >= other.depth:
            return False
        return other.segments[: self.depth] == self.segments

    def __str__(self) -> str:
        return "/".join(self.segments)


@dataclass(frozen=True)
class ScopeNode:
    """A node in the scope hierarchy with aggregated relevance."""

    path: ScopePath
    score: float
    item_count: int
    children: tuple[ScopeNode, ...] = ()


@runtime_checkable
class ScopeScorer(Protocol):
    """Protocol for scoring scopes against a query."""

    async def score_scopes(
        self,
        query: MemoryQuery,
        scope_paths: tuple[ScopePath, ...],
    ) -> tuple[ScopeNode, ...]: ...


class PropagatingScorer:
    """Scores scopes with parent→child score propagation."""

    def __init__(
        self,
        *,
        propagation_factor: float = 0.7,
        semantic_store: SemanticMemoryStore,
    ) -> None:
        self._propagation_factor = propagation_factor
        self._store = semantic_store

    async def score_scopes(
        self,
        query: MemoryQuery,
        scope_paths: tuple[ScopePath, ...],
    ) -> tuple[ScopeNode, ...]:
        """Score scopes by sampling items, then propagate parent→child."""
        if not scope_paths:
            return ()

        # 1. Compute base scores by sampling items from each scope path
        base_scores: dict[str, float] = {}
        item_counts: dict[str, int] = {}

        for path in scope_paths:
            sample_query = MemoryQuery(
                text=query.text,
                scope=query.scope,
                scopes=query.scopes,
                min_confidence=query.min_confidence,
                limit=5,
            )
            results = await self._store.search(query=sample_query)
            # Filter to items whose keys start with this scope path
            path_str = str(path)
            matching = [r for r in results if r.item.key.startswith(path_str)]

            if matching:
                base_scores[path_str] = sum(r.combined_score for r in matching) / len(matching)
                item_counts[path_str] = len(matching)
            else:
                base_scores[path_str] = 0.0
                item_counts[path_str] = 0

        # 2. Propagate: child_score += parent_score * propagation_factor
        propagated: dict[str, float] = dict(base_scores)
        sorted_paths = sorted(scope_paths, key=lambda p: p.depth)

        for path in sorted_paths:
            path_str = str(path)
            if path.parent is not None:
                parent_str = str(path.parent)
                if parent_str in propagated:
                    propagated[path_str] += propagated[parent_str] * self._propagation_factor

        # 3. Build ScopeNodes and sort by score descending
        nodes = tuple(
            ScopeNode(
                path=path,
                score=propagated.get(str(path), 0.0),
                item_count=item_counts.get(str(path), 0),
            )
            for path in scope_paths
        )
        return tuple(sorted(nodes, key=lambda n: n.score, reverse=True))
