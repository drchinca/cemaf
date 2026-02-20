"""Tests for provenance tracking models."""

import pytest

from cemaf.core.enums import ExclusionReason
from cemaf.core.provenance import ProvenanceChain, ProvenanceLink, SourceReference
from cemaf.core.types import AgentID, NodeID, ProvenanceID, RunID


class TestSourceReference:
    """Tests for SourceReference frozen dataclass."""

    def test_create_included_source(self) -> None:
        ref = SourceReference(
            source_id="src-1",
            source_type="document",
            token_count=500,
            priority=10,
            included=True,
        )
        assert ref.source_id == "src-1"
        assert ref.included is True
        assert ref.exclusion_reason is None

    def test_create_excluded_source(self) -> None:
        ref = SourceReference(
            source_id="src-2",
            source_type="glossary",
            token_count=2000,
            priority=1,
            included=False,
            exclusion_reason=ExclusionReason.BUDGET_EXCEEDED,
        )
        assert ref.included is False
        assert ref.exclusion_reason == ExclusionReason.BUDGET_EXCEEDED

    def test_frozen(self) -> None:
        ref = SourceReference(source_id="src-1", source_type="doc", token_count=100)
        with pytest.raises(AttributeError):
            ref.source_id = "changed"  # type: ignore[misc]

    def test_roundtrip_serialization(self) -> None:
        ref = SourceReference(
            source_id="src-1",
            source_type="doc",
            token_count=100,
            priority=5,
            included=False,
            exclusion_reason=ExclusionReason.STALE,
        )
        data = ref.to_dict()
        restored = SourceReference.from_dict(data)
        assert restored == ref

    def test_serialization_without_exclusion(self) -> None:
        ref = SourceReference(source_id="s1", source_type="t", token_count=10)
        data = ref.to_dict()
        assert "exclusion_reason" not in data
        restored = SourceReference.from_dict(data)
        assert restored.exclusion_reason is None


class TestProvenanceLink:
    """Tests for ProvenanceLink frozen dataclass."""

    def test_create_minimal(self) -> None:
        link = ProvenanceLink(
            id=ProvenanceID("prov-1"),
            llm_call_id="llm-1",
        )
        assert link.id == "prov-1"
        assert link.context_sources == ()
        assert link.cost_usd == 0.0

    def test_included_excluded_sources(self) -> None:
        sources = (
            SourceReference(source_id="a", source_type="doc", token_count=100, included=True),
            SourceReference(
                source_id="b",
                source_type="doc",
                token_count=200,
                included=False,
                exclusion_reason=ExclusionReason.LOW_PRIORITY,
            ),
            SourceReference(source_id="c", source_type="doc", token_count=300, included=True),
        )
        link = ProvenanceLink(
            id=ProvenanceID("prov-1"),
            llm_call_id="llm-1",
            context_sources=sources,
        )
        assert len(link.included_sources) == 2
        assert len(link.excluded_sources) == 1
        assert link.total_source_tokens == 400

    def test_roundtrip_serialization(self) -> None:
        link = ProvenanceLink(
            id=ProvenanceID("prov-1"),
            llm_call_id="llm-1",
            node_id=NodeID("node-1"),
            agent_id=AgentID("agent-1"),
            context_sources=(SourceReference(source_id="s1", source_type="doc", token_count=100),),
            context_hash="abc123",
            citation_ids=("cit-1", "cit-2"),
            patch_ids=("patch-1",),
            budget_utilization=0.75,
            cost_usd=0.003,
        )
        data = link.to_dict()
        restored = ProvenanceLink.from_dict(data)
        assert restored.id == link.id
        assert restored.node_id == link.node_id
        assert restored.citation_ids == link.citation_ids
        assert restored.cost_usd == link.cost_usd
        assert len(restored.context_sources) == 1


class TestProvenanceChain:
    """Tests for ProvenanceChain."""

    @pytest.fixture()
    def sample_chain(self) -> ProvenanceChain:
        links = (
            ProvenanceLink(
                id=ProvenanceID("prov-1"),
                llm_call_id="llm-1",
                node_id=NodeID("node-a"),
                agent_id=AgentID("researcher"),
                citation_ids=("c1",),
                cost_usd=0.01,
                context_sources=(SourceReference(source_id="doc-1", source_type="doc", token_count=100),),
            ),
            ProvenanceLink(
                id=ProvenanceID("prov-2"),
                llm_call_id="llm-2",
                node_id=NodeID("node-b"),
                agent_id=AgentID("writer"),
                citation_ids=("c2", "c3"),
                cost_usd=0.02,
                context_sources=(SourceReference(source_id="doc-2", source_type="doc", token_count=200),),
            ),
        )
        return ProvenanceChain(run_id=RunID("run-1"), links=links)

    def test_append(self) -> None:
        chain = ProvenanceChain(run_id=RunID("run-1"))
        new_link = ProvenanceLink(id=ProvenanceID("prov-1"), llm_call_id="llm-1")
        updated = chain.append(link=new_link)
        assert len(updated.links) == 1
        assert len(chain.links) == 0  # original unchanged

    def test_filter_by_node(self, sample_chain: ProvenanceChain) -> None:
        result = sample_chain.filter_by_node(node_id=NodeID("node-a"))
        assert len(result) == 1
        assert result[0].id == "prov-1"

    def test_filter_by_agent(self, sample_chain: ProvenanceChain) -> None:
        result = sample_chain.filter_by_agent(agent_id=AgentID("writer"))
        assert len(result) == 1
        assert result[0].id == "prov-2"

    def test_get_by_llm_call(self, sample_chain: ProvenanceChain) -> None:
        link = sample_chain.get_by_llm_call(llm_call_id="llm-2")
        assert link is not None
        assert link.id == "prov-2"

    def test_get_by_llm_call_not_found(self, sample_chain: ProvenanceChain) -> None:
        assert sample_chain.get_by_llm_call(llm_call_id="nonexistent") is None

    def test_total_cost(self, sample_chain: ProvenanceChain) -> None:
        assert sample_chain.total_cost_usd == pytest.approx(0.03)

    def test_all_citation_ids(self, sample_chain: ProvenanceChain) -> None:
        assert sample_chain.all_citation_ids == ("c1", "c2", "c3")

    def test_all_source_ids(self, sample_chain: ProvenanceChain) -> None:
        assert sample_chain.all_source_ids == ("doc-1", "doc-2")

    def test_roundtrip_serialization(self, sample_chain: ProvenanceChain) -> None:
        data = sample_chain.to_dict()
        restored = ProvenanceChain.from_dict(data)
        assert restored.run_id == sample_chain.run_id
        assert len(restored.links) == len(sample_chain.links)
        assert restored.total_cost_usd == pytest.approx(sample_chain.total_cost_usd)

    def test_new_link_id(self) -> None:
        link_id = ProvenanceChain.new_link_id()
        assert link_id.startswith("prov_")
