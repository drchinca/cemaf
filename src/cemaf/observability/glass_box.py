"""Glass Box Report Generator - Full audit trail for DAG runs."""

from dataclasses import dataclass, field
from typing import Any

from cemaf.core.provenance import ProvenanceChain, ProvenanceLink, SourceReference
from cemaf.core.types import JSON, RunID
from cemaf.observability.run_logger import LLMCall, RunRecord


@dataclass(frozen=True)
class CostBreakdown:
    """Per-model and per-node cost breakdown."""

    total_cost_usd: float
    by_model: dict[str, float]
    by_node: dict[str, float]
    by_agent: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_cost_usd": self.total_cost_usd,
            "by_model": dict(self.by_model),
            "by_node": dict(self.by_node),
            "by_agent": dict(self.by_agent),
        }


@dataclass(frozen=True)
class TokenAudit:
    """Per-source, per-node, and per-agent token breakdown."""

    total_input_tokens: int
    total_output_tokens: int
    by_node: dict[str, dict[str, int]]
    by_agent: dict[str, dict[str, int]]
    by_source: dict[str, int]
    sources_included: int
    sources_excluded: int
    exclusion_reasons: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "by_node": dict(self.by_node),
            "by_agent": dict(self.by_agent),
            "by_source": dict(self.by_source),
            "sources_included": self.sources_included,
            "sources_excluded": self.sources_excluded,
            "exclusion_reasons": dict(self.exclusion_reasons),
        }


@dataclass(frozen=True)
class DecisionStep:
    """What an LLM saw vs what it decided."""

    llm_call_id: str
    node_id: str | None
    agent_id: str | None
    model: str
    sources_seen: tuple[str, ...]
    sources_excluded: tuple[str, ...]
    citation_ids: tuple[str, ...]
    output_preview: str
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "llm_call_id": self.llm_call_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "model": self.model,
            "sources_seen": list(self.sources_seen),
            "sources_excluded": list(self.sources_excluded),
            "citation_ids": list(self.citation_ids),
            "output_preview": self.output_preview,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class CitationCoverage:
    """Verification: did the LLM see what it cited?"""

    total_citations: int
    verified_citations: int
    unverified_citations: int
    coverage_ratio: float
    unverified_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_citations": self.total_citations,
            "verified_citations": self.verified_citations,
            "unverified_citations": self.unverified_citations,
            "coverage_ratio": self.coverage_ratio,
            "unverified_ids": list(self.unverified_ids),
        }


@dataclass(frozen=True)
class GlassBoxReport:
    """Complete audit trail for a DAG run."""

    run_id: RunID
    success: bool
    provenance_chain: ProvenanceChain | None
    citation_coverage: CitationCoverage
    token_audit: TokenAudit
    cost_breakdown: CostBreakdown
    decision_trace: tuple[DecisionStep, ...]
    quality_metrics: JSON = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "run_id": self.run_id,
            "success": self.success,
            "provenance_chain": self.provenance_chain.to_dict() if self.provenance_chain else None,
            "citation_coverage": self.citation_coverage.to_dict(),
            "token_audit": self.token_audit.to_dict(),
            "cost_breakdown": self.cost_breakdown.to_dict(),
            "decision_trace": [step.to_dict() for step in self.decision_trace],
            "quality_metrics": self.quality_metrics,
        }


class GlassBoxReporter:
    """Generates glass box audit reports from completed RunRecords."""

    def generate(self, record: RunRecord) -> GlassBoxReport:
        """Generate a complete glass box report from a RunRecord."""
        return GlassBoxReport(
            run_id=RunID(record.run_id),
            success=record.success,
            provenance_chain=record.provenance_chain,
            citation_coverage=self.verify_citation_coverage(record=record),
            token_audit=self.generate_token_audit(record=record),
            cost_breakdown=self._generate_cost_breakdown(record=record),
            decision_trace=self.generate_decision_trace(record=record),
            quality_metrics=self._generate_quality_metrics(record=record),
        )

    def generate_decision_trace(self, *, record: RunRecord) -> tuple[DecisionStep, ...]:
        """Build trace showing what each LLM saw vs decided."""
        chain = record.provenance_chain
        llm_index: dict[str, LLMCall] = {call.id: call for call in record.llm_calls}
        steps: list[DecisionStep] = []

        if chain is None:
            # No provenance chain — build minimal trace from LLM calls
            for call in record.llm_calls:
                steps.append(
                    DecisionStep(
                        llm_call_id=call.id,
                        node_id=call.node_id,
                        agent_id=call.agent_id,
                        model=call.model,
                        sources_seen=call.context_sources_used,
                        sources_excluded=(),
                        citation_ids=(),
                        output_preview=call.output[:200] if call.output else "",
                        cost_usd=call.cost_usd,
                    )
                )
            return tuple(steps)

        for link in chain.links:
            llm_call = llm_index.get(link.llm_call_id)
            model = llm_call.model if llm_call else ""
            output = llm_call.output if llm_call else ""
            cost = link.cost_usd

            included = tuple(s.source_id for s in link.included_sources)
            excluded = tuple(s.source_id for s in link.excluded_sources)

            steps.append(
                DecisionStep(
                    llm_call_id=link.llm_call_id,
                    node_id=str(link.node_id) if link.node_id else None,
                    agent_id=str(link.agent_id) if link.agent_id else None,
                    model=model,
                    sources_seen=included,
                    sources_excluded=excluded,
                    citation_ids=link.citation_ids,
                    output_preview=output[:200],
                    cost_usd=cost,
                )
            )

        return tuple(steps)

    def generate_token_audit(self, *, record: RunRecord) -> TokenAudit:
        """Build per-source, per-node, per-agent token breakdown."""
        total_input = sum(c.input_tokens for c in record.llm_calls)
        total_output = sum(c.output_tokens for c in record.llm_calls)

        by_node: dict[str, dict[str, int]] = {}
        by_agent: dict[str, dict[str, int]] = {}

        for call in record.llm_calls:
            node_key = call.node_id or "unknown"
            agent_key = call.agent_id or "unknown"

            if node_key not in by_node:
                by_node[node_key] = {"input_tokens": 0, "output_tokens": 0}
            by_node[node_key]["input_tokens"] += call.input_tokens
            by_node[node_key]["output_tokens"] += call.output_tokens

            if agent_key not in by_agent:
                by_agent[agent_key] = {"input_tokens": 0, "output_tokens": 0}
            by_agent[agent_key]["input_tokens"] += call.input_tokens
            by_agent[agent_key]["output_tokens"] += call.output_tokens

        # Source-level token tracking from provenance chain
        by_source: dict[str, int] = {}
        sources_included = 0
        sources_excluded = 0
        exclusion_reasons: dict[str, int] = {}

        if record.provenance_chain:
            all_sources = self._collect_all_sources(chain=record.provenance_chain)
            for source in all_sources:
                by_source[source.source_id] = by_source.get(source.source_id, 0) + source.token_count
                if source.included:
                    sources_included += 1
                else:
                    sources_excluded += 1
                    reason = source.exclusion_reason.value if source.exclusion_reason else "unknown"
                    exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

        return TokenAudit(
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            by_node=by_node,
            by_agent=by_agent,
            by_source=by_source,
            sources_included=sources_included,
            sources_excluded=sources_excluded,
            exclusion_reasons=exclusion_reasons,
        )

    def verify_citation_coverage(self, *, record: RunRecord) -> CitationCoverage:
        """Check if every citation refers to a source the LLM actually saw."""
        if not record.provenance_chain:
            return CitationCoverage(
                total_citations=0,
                verified_citations=0,
                unverified_citations=0,
                coverage_ratio=1.0,
                unverified_ids=(),
            )

        chain = record.provenance_chain
        all_citation_ids = chain.all_citation_ids
        if not all_citation_ids:
            return CitationCoverage(
                total_citations=0,
                verified_citations=0,
                unverified_citations=0,
                coverage_ratio=1.0,
                unverified_ids=(),
            )

        # Build map: citation_id → link that produced it
        citation_to_link: dict[str, ProvenanceLink] = {}
        for link in chain.links:
            for cid in link.citation_ids:
                citation_to_link[cid] = link

        verified = 0
        unverified_ids: list[str] = []

        for cid in all_citation_ids:
            link = citation_to_link.get(cid)
            if link and len(link.included_sources) > 0:
                verified += 1
            else:
                unverified_ids.append(cid)

        total = len(all_citation_ids)
        ratio = verified / total if total > 0 else 1.0

        return CitationCoverage(
            total_citations=total,
            verified_citations=verified,
            unverified_citations=len(unverified_ids),
            coverage_ratio=ratio,
            unverified_ids=tuple(unverified_ids),
        )

    def _generate_cost_breakdown(self, *, record: RunRecord) -> CostBreakdown:
        """Build per-model, per-node, per-agent cost breakdown."""
        by_model: dict[str, float] = {}
        by_node: dict[str, float] = {}
        by_agent: dict[str, float] = {}

        for call in record.llm_calls:
            model_key = call.model or "unknown"
            by_model[model_key] = by_model.get(model_key, 0.0) + call.cost_usd

            node_key = call.node_id or "unknown"
            by_node[node_key] = by_node.get(node_key, 0.0) + call.cost_usd

            agent_key = call.agent_id or "unknown"
            by_agent[agent_key] = by_agent.get(agent_key, 0.0) + call.cost_usd

        return CostBreakdown(
            total_cost_usd=record.total_cost_usd,
            by_model=by_model,
            by_node=by_node,
            by_agent=by_agent,
        )

    def _generate_quality_metrics(self, *, record: RunRecord) -> JSON:
        """Compute quality metrics from record."""
        total_llm = len(record.llm_calls)
        total_patches = len(record.patches)

        metrics: dict[str, Any] = {
            "total_llm_calls": total_llm,
            "total_patches": total_patches,
            "total_tool_calls": len(record.tool_calls),
            "run_success": record.success,
            "duration_ms": record.duration_ms,
        }

        if record.provenance_chain:
            chain = record.provenance_chain
            metrics["provenance_links"] = len(chain.links)
            metrics["unique_sources"] = len(chain.all_source_ids)
            metrics["total_citations"] = len(chain.all_citation_ids)

        return metrics

    @staticmethod
    def _collect_all_sources(*, chain: ProvenanceChain) -> tuple[SourceReference, ...]:
        """Collect all source references across all provenance links."""
        sources: list[SourceReference] = []
        for link in chain.links:
            sources.extend(link.context_sources)
        return tuple(sources)
