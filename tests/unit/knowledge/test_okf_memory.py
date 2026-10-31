"""Research-session boundaries: budgeted discovery, revisions, and stale proposals."""

from datetime import datetime
from pathlib import Path

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.ingestion import OKFAdapter
from cemaf.knowledge import OKFBundle, OKFDocument


def note(name: str, body: str = "Recorded observation.", **metadata: object) -> OKFDocument:
    return OKFDocument(path=f"notes/{name}.md", frontmatter={"type": "Finding", **metadata}, body=body)


async def test_budgeted_catalog_visits_every_entry_once() -> None:
    bundle = OKFBundle(tuple(note(f"finding-{i:03}", body="Evidence. " * 1000) for i in range(125)))
    adapter = OKFAdapter(
        bundle_id="project", revision=bundle.revision, token_estimator=SimpleTokenEstimator(chars_per_token=1)
    )
    budget = TokenBudget(max_tokens=360, reserved_for_output=60)
    visited = []
    offset = 0
    while True:
        page = await adapter.adapt_catalog(bundle, budget, directory="notes", offset=offset)
        assert page.source.token_count == len(page.source.content) <= budget.available_tokens
        assert page.source.metadata["bundle_revision"] == bundle.revision
        assert "Evidence." not in page.source.content
        assert page.total_entries == 125
        visited.extend(
            line.split(" | ")[0] for line in page.source.content.splitlines() if line.startswith("- ")
        )
        if page.next_offset is None:
            break
        assert page.next_offset > offset
        offset = page.next_offset
    assert visited == [f"- /notes/finding-{i:03}.md" for i in range(125)]


async def test_catalog_boundary_counts_marker_and_output_reservation() -> None:
    bundle = OKFBundle((note("a"), note("b")))
    adapter = OKFAdapter(bundle_id="project", token_estimator=SimpleTokenEstimator(chars_per_token=1))
    content = bundle.catalog("notes", limit=1)
    budget = TokenBudget(max_tokens=len(content) + 20, reserved_for_output=20)
    result = await adapter.adapt_catalog(bundle, budget, directory="notes", limit=1)
    assert result.source.content == content
    assert result.source.token_count == budget.available_tokens
    assert result.next_offset == 1
    with pytest.raises(ValueError, match="budget"):
        await adapter.adapt_catalog(
            bundle,
            TokenBudget(max_tokens=len(content) + 19, reserved_for_output=20),
            directory="notes",
            limit=1,
        )


async def test_oversize_descriptions_can_be_omitted_without_skipping_identity() -> None:
    bundle = OKFBundle((note("a", description="Large metadata. " * 1000), note("b")))
    budget = TokenBudget(max_tokens=150, reserved_for_output=0)
    adapter = OKFAdapter(bundle_id="project", token_estimator=SimpleTokenEstimator(chars_per_token=1))
    with pytest.raises(ValueError, match="omit descriptions"):
        await adapter.adapt_catalog(bundle, budget, directory="notes")
    page = await adapter.adapt_catalog(bundle, budget, directory="notes", include_descriptions=False)
    assert "/notes/a.md" in page.source.content
    assert "Large metadata" not in page.source.content


async def test_catalog_empty_invalid_offsets_and_changed_revision() -> None:
    bundle = OKFBundle(())
    adapter = OKFAdapter(bundle_id="project", revision=bundle.revision)
    budget = TokenBudget(max_tokens=200, reserved_for_output=0)
    page = await adapter.adapt_catalog(bundle, budget)
    assert page.source.content == "# /"
    assert page.total_entries == 0 and page.next_offset is None
    for kwargs in ({"offset": -1}, {"offset": 1}, {"limit": 0}, {"directory": "../escape"}):
        with pytest.raises(ValueError):
            await adapter.adapt_catalog(bundle, budget, **kwargs)
    with pytest.raises(ValueError, match="snapshot changed"):
        await adapter.adapt_catalog(bundle.with_document(note("new")), budget)


async def test_catalog_handles_nonadditive_estimator() -> None:
    class FramedEstimator:
        def estimate(self, text: str) -> int:
            # More entries can remove the continuation marker, reducing total cost.
            return len(text) + (1000 if "Next catalog offset" in text else 0)

    bundle = OKFBundle((note("a"), note("b")))
    adapter = OKFAdapter(bundle_id="project", token_estimator=FramedEstimator())
    page = await adapter.adapt_catalog(
        bundle, TokenBudget(max_tokens=200, reserved_for_output=0), directory="notes"
    )
    assert page.next_offset is None
    assert page.source.metadata["entry_count"] == 2


def test_diff_tracks_concepts_assets_and_exact_bytes(tmp_path: Path) -> None:
    previous = OKFBundle(
        (note("unchanged"), note("modified"), note("removed")),
        {"index.md": b"old index", "data.csv": b"same", "removed.csv": b"old"},
    )
    current = OKFBundle(
        (note("added"), note("modified", body="Revised observation."), note("unchanged")),
        {"index.md": b"new index", "data.csv": b"same", "added.csv": b"new"},
    )
    delta = current.diff(previous)
    assert not delta.empty
    assert delta.before_revision == previous.revision
    assert delta.after_revision == current.revision
    assert delta.added == ("notes/added",)
    assert delta.modified == ("notes/modified",)
    assert delta.removed == ("notes/removed",)
    assert delta.supporting_added == ("added.csv",)
    assert delta.supporting_modified == ("index.md",)
    assert delta.supporting_removed == ("removed.csv",)
    reloaded = OKFBundle.load(current.write(tmp_path / "snapshot"))
    assert reloaded.diff(current).empty
    reordered = OKFBundle(tuple(reversed(current.documents)), current.supporting_files)
    assert reordered.diff(current).empty


def test_supporting_only_changes_and_moves() -> None:
    previous = OKFBundle((note("a"),), {"compute.sql": b"SELECT 1;"})
    current = OKFBundle(previous.documents, {"compute.sql": b"SELECT 2;"})
    delta = current.diff(previous)
    assert not delta.empty and delta.supporting_modified == ("compute.sql",)
    assert delta.added == delta.modified == delta.removed == ()
    moved = previous.without_document("notes/a").with_document(note("b"))
    delta = moved.diff(previous)
    assert delta.removed == ("notes/a",) and delta.added == ("notes/b",)
    with pytest.raises(KeyError):
        moved.without_document("notes/missing")
    assert previous.get("notes/a").body == "Recorded observation."


def test_proposal_base_check_handles_conflicts_and_wrong_identity() -> None:
    original = note("a")
    proposed = original.propose(body="New interpretation.", actor="cemaf/research", run_id="run-2")
    assert proposed.proposal_matches(original)
    assert not proposed.proposal_matches(note("a", body="Concurrently revised."))
    assert not proposed.proposal_matches(note("b"))  # same bytes, different concept
    assert not original.proposal_matches(original)
    malformed = note("a", cemaf_proposal={"base_content_hash": original.content_hash, "run_id": " "})
    assert not malformed.proposal_matches(original)
    raw = "---\ntype: Finding\n---\nObservation.\n"
    old = OKFDocument.parse(path="notes/a.md", text=raw)
    new = OKFDocument.parse(path="notes/a.md", text=raw.replace("---\ntype", "---\n# Comment\ntype"))
    assert old.body == new.body
    assert not old.propose(body="Change.", actor="cemaf/research", run_id="r").proposal_matches(new)


def test_naive_staleness_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        note("a", stale_after="2026-10-30T00:00:00Z").is_stale(now=datetime(2026, 10, 30))


def test_supporting_mapping_is_copied_at_snapshot_boundary() -> None:
    files = {"index.md": b"Original"}
    bundle = OKFBundle((note("a"),), files)
    revision = bundle.revision
    files["index.md"] = b"Externally changed"
    assert bundle.revision == revision
