"""Unit tests for CiteableChunk/RetrievalQuery/EntityRef validation."""

import pytest

from cemaf.citation.models import Citation
from cemaf.datasources.models import CiteableChunk, EntityRef, RetrievalQuery


def _citation(**overrides: object) -> Citation:
    defaults: dict[str, object] = {
        "id": "c1",
        "source_id": "fake-crm",
        "source_type": "document",
        "url": "https://example.com/doc",
    }
    defaults.update(overrides)
    return Citation(**defaults)  # type: ignore[arg-type]


class TestRetrievalQuery:
    def test_defaults(self) -> None:
        query = RetrievalQuery(text="find orders")
        assert query.entities == ()
        assert query.top_k == 8
        assert query.timeout_ms == 3_000


class TestEntityRef:
    def test_construction(self) -> None:
        ref = EntityRef(id="order-42", label="Order 42")
        assert ref.entity_type == ""


class TestCiteableChunk:
    def test_valid_chunk_constructs(self) -> None:
        chunk = CiteableChunk(
            chunk_id="ch1", content="hi", citation=_citation(), token_count=5, source_kind="datasource"
        )
        assert chunk.priority == 80
        assert chunk.effective_priority == 80

    def test_effective_priority_includes_tenant_offset(self) -> None:
        chunk = CiteableChunk(
            chunk_id="ch1",
            content="hi",
            citation=_citation(),
            token_count=5,
            source_kind="kg",
            tenant_offset=5,
        )
        assert chunk.priority == 100
        assert chunk.effective_priority == 105

    def test_invalid_source_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="source_kind"):
            CiteableChunk(
                chunk_id="ch1", content="hi", citation=_citation(), token_count=5, source_kind="bogus"
            )

    def test_missing_citation_source_id_raises(self) -> None:
        with pytest.raises(ValueError, match="source_id"):
            CiteableChunk(
                chunk_id="ch1",
                content="hi",
                citation=_citation(source_id=""),
                token_count=5,
                source_kind="datasource",
            )

    def test_missing_locator_raises(self) -> None:
        with pytest.raises(ValueError, match="locator"):
            CiteableChunk(
                chunk_id="ch1",
                content="hi",
                citation=_citation(url=None, context_path=None, section=None, page=None),
                token_count=5,
                source_kind="datasource",
            )

    def test_tenant_offset_out_of_bound_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_offset"):
            CiteableChunk(
                chunk_id="ch1",
                content="hi",
                citation=_citation(),
                token_count=5,
                source_kind="datasource",
                tenant_offset=11,
            )

    def test_tenant_offset_at_bound_is_valid(self) -> None:
        chunk = CiteableChunk(
            chunk_id="ch1",
            content="hi",
            citation=_citation(),
            token_count=5,
            source_kind="datasource",
            tenant_offset=-10,
        )
        assert chunk.effective_priority == 70
