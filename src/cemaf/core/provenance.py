"""Provenance tracking for glass box audit trail."""

from dataclasses import dataclass, field
from typing import Any

from cemaf.core.enums import ExclusionReason
from cemaf.core.types import AgentID, NodeID, ProvenanceID, RunID
from cemaf.core.utils import generate_id, utc_now


@dataclass(frozen=True)
class SourceReference:
    """A context source as seen by a single LLM call."""

    source_id: str
    source_type: str
    token_count: int
    priority: int = 0
    included: bool = True
    exclusion_reason: ExclusionReason | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "token_count": self.token_count,
            "priority": self.priority,
            "included": self.included,
        }
        if self.exclusion_reason is not None:
            result["exclusion_reason"] = self.exclusion_reason.value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceReference:
        """Deserialize from dictionary."""
        exclusion = data.get("exclusion_reason")
        return cls(
            source_id=data["source_id"],
            source_type=data["source_type"],
            token_count=data["token_count"],
            priority=data.get("priority", 0),
            included=data.get("included", True),
            exclusion_reason=ExclusionReason(exclusion) if exclusion else None,
        )


@dataclass(frozen=True)
class ProvenanceLink:
    """Cross-references every artifact produced during a single LLM call."""

    id: ProvenanceID
    llm_call_id: str
    node_id: NodeID | None = None
    agent_id: AgentID | None = None
    context_sources: tuple[SourceReference, ...] = ()
    context_hash: str = ""
    citation_ids: tuple[str, ...] = ()
    patch_ids: tuple[str, ...] = ()
    budget_utilization: float = 0.0
    cost_usd: float = 0.0
    timestamp: str = field(default_factory=lambda: utc_now().isoformat())

    @property
    def included_sources(self) -> tuple[SourceReference, ...]:
        """Sources actually sent to the LLM."""
        return tuple(s for s in self.context_sources if s.included)

    @property
    def excluded_sources(self) -> tuple[SourceReference, ...]:
        """Sources excluded from the LLM call."""
        return tuple(s for s in self.context_sources if not s.included)

    @property
    def total_source_tokens(self) -> int:
        """Total tokens from included sources."""
        return sum(s.token_count for s in self.included_sources)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "llm_call_id": self.llm_call_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "context_sources": [s.to_dict() for s in self.context_sources],
            "context_hash": self.context_hash,
            "citation_ids": list(self.citation_ids),
            "patch_ids": list(self.patch_ids),
            "budget_utilization": self.budget_utilization,
            "cost_usd": self.cost_usd,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceLink:
        """Deserialize from dictionary."""
        return cls(
            id=ProvenanceID(data["id"]),
            llm_call_id=data["llm_call_id"],
            node_id=NodeID(data["node_id"]) if data.get("node_id") else None,
            agent_id=AgentID(data["agent_id"]) if data.get("agent_id") else None,
            context_sources=tuple(SourceReference.from_dict(s) for s in data.get("context_sources", [])),
            context_hash=data.get("context_hash", ""),
            citation_ids=tuple(data.get("citation_ids", [])),
            patch_ids=tuple(data.get("patch_ids", [])),
            budget_utilization=data.get("budget_utilization", 0.0),
            cost_usd=data.get("cost_usd", 0.0),
            timestamp=data.get("timestamp", ""),
        )


@dataclass(frozen=True)
class ProvenanceChain:
    """Ordered chain of ProvenanceLinks for an entire DAG run."""

    run_id: RunID
    links: tuple[ProvenanceLink, ...] = ()

    def append(self, link: ProvenanceLink) -> ProvenanceChain:
        """Return new chain with link appended."""
        return ProvenanceChain(
            run_id=self.run_id,
            links=self.links + (link,),
        )

    def filter_by_node(self, node_id: NodeID) -> tuple[ProvenanceLink, ...]:
        """Return links for a specific node."""
        return tuple(link for link in self.links if link.node_id == node_id)

    def filter_by_agent(self, agent_id: AgentID) -> tuple[ProvenanceLink, ...]:
        """Return links for a specific agent."""
        return tuple(link for link in self.links if link.agent_id == agent_id)

    def get_by_llm_call(self, llm_call_id: str) -> ProvenanceLink | None:
        """Find link for a specific LLM call."""
        for link in self.links:
            if link.llm_call_id == llm_call_id:
                return link
        return None

    @property
    def total_cost_usd(self) -> float:
        """Sum of all link costs."""
        return sum(link.cost_usd for link in self.links)

    @property
    def all_citation_ids(self) -> tuple[str, ...]:
        """All citation IDs across all links."""
        ids: list[str] = []
        for link in self.links:
            ids.extend(link.citation_ids)
        return tuple(ids)

    @property
    def all_source_ids(self) -> tuple[str, ...]:
        """All unique source IDs across all links."""
        seen: set[str] = set()
        result: list[str] = []
        for link in self.links:
            for source in link.context_sources:
                if source.source_id not in seen:
                    seen.add(source.source_id)
                    result.append(source.source_id)
        return tuple(result)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "run_id": self.run_id,
            "links": [link.to_dict() for link in self.links],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceChain:
        """Deserialize from dictionary."""
        return cls(
            run_id=RunID(data["run_id"]),
            links=tuple(ProvenanceLink.from_dict(link) for link in data.get("links", [])),
        )

    @staticmethod
    def new_link_id() -> ProvenanceID:
        """Generate a new provenance link ID."""
        return ProvenanceID(generate_id(prefix="prov"))
