"""Tests for MarkdownDocSource and PackageDocstringSource."""

from __future__ import annotations

from pathlib import Path

from cemaf.docs_api.index import DocEntryKind
from cemaf.docs_api.sources import MarkdownDocSource, PackageDocstringSource


def test_markdown_source_reads_top_level_md(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Alpha\n\nbody")
    (tmp_path / "b.md").write_text("# Beta\n\n## Section\n\nmore")

    entries = list(MarkdownDocSource(root=tmp_path).load())
    by_id = {e.id: e for e in entries}
    assert "docs/a.md" in by_id
    assert "docs/b.md" in by_id
    assert by_id["docs/a.md"].title == "Alpha"
    assert by_id["docs/a.md"].kind is DocEntryKind.GUIDE


def test_markdown_source_extracts_anchors(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Title\n\n## Section A\n\n### Sub\n\nbody")
    entries = list(MarkdownDocSource(root=tmp_path).load())
    assert len(entries) == 1
    anchors = entries[0].anchors
    assert "Section A" in anchors
    assert "Sub" in anchors


def test_markdown_source_missing_root_is_noop(tmp_path: Path) -> None:
    entries = list(MarkdownDocSource(root=tmp_path / "nope").load())
    assert entries == []


def test_markdown_source_explodes_patterns_sections(tmp_path: Path) -> None:
    patterns_body = (
        "# Design Patterns\n\n"
        "## 1. Protocol-first design\n\nsome content about protocols\n\n"
        "## 2. BYO-X\n\ncontent about bringing your own thing\n\n"
        "## 3. RuntimeServices bundle\n\ncontent about services\n"
    )
    (tmp_path / "patterns.md").write_text(patterns_body)
    entries = list(MarkdownDocSource(root=tmp_path).load())
    by_id = {e.id: e for e in entries}
    # The GUIDE entry is produced, plus one PATTERN per section
    pattern_entries = [e for e in entries if e.kind is DocEntryKind.PATTERN]
    assert len(pattern_entries) == 3
    assert "pattern:1-protocol-first-design" in by_id
    assert "pattern:2-byo-x" in by_id
    assert "pattern:3-runtimeservices-bundle" in by_id
    # Section body contains its own heading
    assert "Protocol-first" in by_id["pattern:1-protocol-first-design"].body


def test_package_docstring_source_loads_cemaf_packages() -> None:
    entries = list(PackageDocstringSource(root_package="cemaf").load())
    ids = {e.id for e in entries}
    # Sanity: we must find at least the core packages we just enriched
    assert "pkg:cemaf" in ids or "pkg:cemaf.orchestration" in ids
    assert "pkg:cemaf.orchestration" in ids
    assert "pkg:cemaf.meta" in ids
    assert "pkg:cemaf.mcp" in ids


def test_package_docstring_source_skips_empty_docs() -> None:
    """Modules without a docstring (or blank) shouldn't produce entries."""
    entries = list(PackageDocstringSource(root_package="cemaf").load())
    # Every produced entry has a non-empty body
    assert all(entry.body.strip() for entry in entries)


def test_package_docstring_source_produces_module_entries_too() -> None:
    entries = list(PackageDocstringSource(root_package="cemaf").load())
    # We know meta/scaffolder.py has a docstring
    module_ids = {e.id for e in entries if e.kind is DocEntryKind.MODULE}
    assert "mod:cemaf.meta.scaffolder" in module_ids
