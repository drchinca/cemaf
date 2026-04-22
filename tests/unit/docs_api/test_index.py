"""Tests for DocIndex — construction, scoring, filtering, lookup."""

from __future__ import annotations

import pytest

from cemaf.docs_api.index import DocEntry, DocEntryKind, DocIndex


def _entry(
    *,
    eid: str,
    kind: DocEntryKind = DocEntryKind.GUIDE,
    title: str = "",
    body: str = "",
    anchors: tuple[str, ...] = (),
) -> DocEntry:
    return DocEntry(id=eid, kind=kind, title=title, body=body, anchors=anchors)


def test_empty_index_is_empty() -> None:
    idx = DocIndex()
    assert len(idx) == 0
    assert idx.all() == ()


def test_add_and_get() -> None:
    idx = DocIndex()
    entry = _entry(eid="a", title="Alpha", body="hello")
    idx.add(entry=entry)
    assert idx.get("a") is entry
    assert len(idx) == 1


def test_add_same_id_overwrites() -> None:
    idx = DocIndex()
    idx.add(entry=_entry(eid="a", title="Old"))
    idx.add(entry=_entry(eid="a", title="New"))
    assert idx.get("a").title == "New"  # type: ignore[union-attr]


def test_search_empty_query_returns_empty() -> None:
    idx = DocIndex([_entry(eid="a", body="anything")])
    assert idx.search(query="") == []
    assert idx.search(query="   ") == []


def test_search_matches_body_tokens() -> None:
    idx = DocIndex(
        [
            _entry(eid="a", title="Page A", body="the runtime services bundle wires everything"),
            _entry(eid="b", title="Page B", body="a completely unrelated topic"),
        ]
    )
    results = idx.search(query="runtime services")
    assert [eid for eid, _ in [(e.id, s) for e, s in results]] == ["a"]


def test_search_title_outweighs_body() -> None:
    """Title hit (x3) beats body-only hit."""
    idx = DocIndex(
        [
            _entry(eid="title_hit", title="runtime services bundle", body="x"),
            _entry(eid="body_hit", title="other", body="the runtime services doc is useful"),
        ]
    )
    results = idx.search(query="runtime services")
    assert results[0][0].id == "title_hit"
    assert results[0][1] > results[1][1]


def test_search_anchor_outweighs_body() -> None:
    idx = DocIndex(
        [
            _entry(
                eid="anchor_hit",
                title="x",
                body="z",
                anchors=("RuntimeServices bundle", "composition root"),
            ),
            _entry(eid="body_hit", title="x", body="runtime services composition"),
        ]
    )
    results = idx.search(query="runtime services")
    # 2 tokens × 2 (anchor) = 4  vs  2 tokens × 1 (body) = 2
    assert results[0][0].id == "anchor_hit"


def test_search_respects_k() -> None:
    idx = DocIndex([_entry(eid=f"e{i}", title=f"run {i}", body="runtime") for i in range(10)])
    results = idx.search(query="runtime", k=3)
    assert len(results) == 3


def test_search_filters_by_kind() -> None:
    idx = DocIndex(
        [
            _entry(eid="g1", kind=DocEntryKind.GUIDE, body="runtime"),
            _entry(eid="p1", kind=DocEntryKind.PACKAGE, body="runtime"),
            _entry(eid="pt1", kind=DocEntryKind.PATTERN, body="runtime"),
        ]
    )
    results = idx.search(query="runtime", kinds=(DocEntryKind.PATTERN,))
    assert len(results) == 1
    assert results[0][0].id == "pt1"


def test_search_ranks_stable_on_tie() -> None:
    """Equal score → sort by id ascending."""
    idx = DocIndex(
        [
            _entry(eid="z_last", body="runtime"),
            _entry(eid="a_first", body="runtime"),
            _entry(eid="m_middle", body="runtime"),
        ]
    )
    results = idx.search(query="runtime", k=3)
    assert [entry.id for entry, _ in results] == ["a_first", "m_middle", "z_last"]


def test_search_returns_no_zero_scores() -> None:
    idx = DocIndex(
        [
            _entry(eid="match", body="runtime services here"),
            _entry(eid="no_match", body="absolutely nothing relevant"),
        ]
    )
    results = idx.search(query="runtime")
    ids = [e.id for e, _ in results]
    assert "match" in ids
    assert "no_match" not in ids


def test_doc_entry_is_frozen() -> None:
    entry = _entry(eid="a", title="x")
    with pytest.raises((AttributeError, Exception)):
        entry.title = "y"  # type: ignore[misc]


def test_camel_case_tokens_match_split_queries() -> None:
    """RuntimeServices in the body should match `runtime services` query.

    CEMAF docs use PascalCase identifiers heavily; natural-language queries
    write them as separate words. Tokenizer must split camelCase.
    """
    idx = DocIndex([_entry(eid="camel", body="The RuntimeServices bundle is the composition root.")])
    results = idx.search(query="runtime services")
    assert len(results) == 1
    assert results[0][0].id == "camel"


def test_snake_case_and_kebab_preserved() -> None:
    idx = DocIndex(
        [
            _entry(eid="snake", body="auto_heal_manager fires when a node fails"),
            _entry(eid="kebab", body="budget-guard caps the run"),
        ]
    )
    assert [e.id for e, _ in idx.search(query="auto heal manager")] == ["snake"]
    assert [e.id for e, _ in idx.search(query="budget guard")] == ["kebab"]
