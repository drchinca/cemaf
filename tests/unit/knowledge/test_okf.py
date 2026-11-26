"""OKF interoperability, evidence preservation, and filesystem boundaries."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.ingestion import AdapterConfig, AdapterOverrides, ContextAdapter, create_adapter
from cemaf.knowledge import OKFBundle, OKFDocument


def concept(path: str = "concept.md", body: str = "A fact.\n", **metadata: object) -> OKFDocument:
    return OKFDocument(path=path, frontmatter={"type": "Research Finding", **metadata}, body=body)


def test_lossless_round_trip_with_extensions_and_crlf() -> None:
    text = (
        "---\r\n# Keep this comment\r\ntype: Unregistered Domain Type\r\n"
        "custom: {enabled: true, weight: 0.5, nested: [one, two]}\r\n"
        "timestamp: 2026-06-01T10:00:00Z\r\n---\r\n# Evidence\r\n\r\nMeasured.\r\n"
    )
    doc = OKFDocument.parse(path="science/finding.md", text=text)
    assert doc.concept_id == "science/finding"
    assert doc.type == "Unregistered Domain Type"
    assert doc.render() == text
    assert doc.trust_tier == "unverified"
    assert doc.status == "stable"
    projected = doc.to_document(bundle_id="project")
    assert projected.metadata["frontmatter"]["custom"]["enabled"] is True
    assert projected.metadata["content_hash"] == doc.content_hash
    assert projected.content == text


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter",
        "---\ntype: Metric\n",
        "---\n- Metric\n---\n",
        "---\ntitle: Missing type\n---\n",
        "---\ntype: ''\n---\n",
        "---\ntype: 42\n---\n",
        "---\ntype: [unterminated\n---\n",
        "---\ntype: !!python/object/apply:os.system ['echo unsafe']\n---\n",
    ],
)
def test_invalid_concepts_fail(text: str) -> None:
    with pytest.raises(ValueError):
        OKFDocument.parse(path="bad.md", text=text)


@pytest.mark.parametrize(
    "path",
    [
        "../escape.md",
        "/absolute.md",
        "a/../../b.md",
        "a\\b.md",
        "index.md",
        "nested/log.md",
        "a.txt",
        "./a.md",
        ".git/a.md",
    ],
)
def test_invalid_concept_paths(path: str) -> None:
    with pytest.raises(ValueError):
        concept(path)


@pytest.mark.parametrize(
    ("verified", "expected"),
    [
        ({"by": "human:researcher", "at": "2026-06-01T00:00:00Z"}, "human-reviewed"),
        ([{"by": "process:check"}, {"by": "human:reviewer"}], "human-reviewed"),
        ([{"by": "process:check"}], "machine-confirmed"),
        ([], "unverified"),
        ({}, "unverified"),
        (None, "unverified"),
    ],
)
def test_trust_mapping_and_list(verified: object, expected: str) -> None:
    assert concept(verified=verified).trust_tier == expected


def test_stale_boundary_and_missing_optional_metadata() -> None:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    assert concept(stale_after=now).is_stale(now=now)
    assert concept(stale_after="2026-10-30T00:00:00Z").is_stale(now=now)
    assert not concept(stale_after="2026-10-31T00:00:00Z").is_stale(now=now)
    assert not concept().is_stale(now=now)
    assert not concept(stale_after="not a timestamp").is_stale(now=now)


def test_commonmark_links_and_resolution() -> None:
    doc = concept(
        "findings/result.md",
        body="""[Root](/data/table.md#schema)
[Relative](../data/table.md "A title")
[Reference][dataset]
[Space](../data/a%20b.md)
[Self](#details)
[Future](./future.md)
[External](https://example.org/a.md)
[Escape](../../outside.md)
[Encoded escape](%2E%2E/%2E%2E/outside.md)
[Asset](../figure.png)
![Image](../not-a-concept.md)
`[Inline code](../not-a-link.md)`

```
[Code](/not-a-link.md)
```

[dataset]: ../data/table.md
""",
    )
    targets = {doc.resolve_link(href) for href in doc.links()}
    assert targets == {"data/table", "data/a b", "findings/result", "findings/future", None}
    assert not any("not-a-" in href for href in doc.links())


def test_bundle_preserves_reserved_files_assets_and_revision(tmp_path: Path) -> None:
    bundle = OKFBundle(
        documents=(concept("a.md"), concept("nested/b.md")),
        supporting_files={
            "index.md": b'---\nokf_version: "0.9"\n---\n# Bundle\n',
            "nested/index.md": b"# Concepts\n",
            "log.md": b"# History\n## 2026-10-30\n* Added concepts.\n",
            "references/calculation.sql": b"SELECT 1;\n",
            "figure.png": b"\x89PNG",
        },
    )
    root = bundle.write(tmp_path / "source")
    loaded = OKFBundle.load(root)
    assert loaded.revision == bundle.revision
    assert loaded.supporting_files == bundle.supporting_files
    exported = loaded.write(tmp_path / "export")
    assert OKFBundle.load(exported).revision == loaded.revision
    with pytest.raises(ValueError, match="outside"):
        loaded.write(root)
    with pytest.raises(ValueError, match="outside"):
        loaded.write(root / "proposal")
    with pytest.raises(FileExistsError):
        loaded.write(exported)
    assert OKFBundle.load(root).revision == bundle.revision


def test_bundle_rejects_symlinks_and_invalid_supporting_paths(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    secret = tmp_path / "outside.md"
    secret.write_text("outside")
    (root / "linked.md").symlink_to(secret)
    with pytest.raises(ValueError, match="symlinks"):
        OKFBundle.load(root)
    for path in ("../escape", "/absolute", ".", "concept.md"):
        with pytest.raises(ValueError):
            OKFBundle((), {path: b"bad"})
    with pytest.raises(ValueError, match="collision"):
        OKFBundle((concept("a.md"), concept("a.md/b.md")))


def test_proposals_clear_verification_and_preserve_base(tmp_path: Path) -> None:
    original = concept(verified={"by": "human:reviewer"}, custom={"unit": "seconds"})
    bundle = OKFBundle((original,))
    source = bundle.write(tmp_path / "source")
    proposal = original.propose(body="A revised finding.\n", actor="cemaf/researcher", run_id="run-1")
    assert proposal.trust_tier == "unverified"
    assert proposal.status == "draft"
    assert proposal.frontmatter["custom"] == original.frontmatter["custom"]
    assert proposal.frontmatter["cemaf_proposal"] == {
        "run_id": "run-1",
        "base_content_hash": original.content_hash,
    }
    revised = bundle.with_document(proposal)
    assert revised.revision != bundle.revision
    revised.write(tmp_path / "proposal")
    assert OKFBundle.load(source).revision == bundle.revision
    assert original.trust_tier == "human-reviewed"


def test_progressive_disclosure_omits_bodies_and_other_directories() -> None:
    bundle = OKFBundle(
        tuple(
            concept(
                f"research/finding-{i}.md",
                body="Long experimental evidence. " * 1000,
                title=f"Finding {i}",
                description="An experimental result.",
            )
            for i in range(40)
        )
        + (concept("operations/runbook.md"),)
    )
    assert bundle.catalog() == "# /\n- /operations/\n- /research/"
    catalog = bundle.catalog("research")
    assert "experimental evidence" not in catalog
    assert "runbook" not in catalog
    estimator = SimpleTokenEstimator()
    full_tokens = sum(estimator.estimate(doc.render()) for doc in bundle.documents)
    assert estimator.estimate(catalog) < full_tokens / 100
    assert bundle.get("research/finding-0").body.startswith("Long experimental")


async def test_context_adapter_factory_budget_and_provenance() -> None:
    estimator = SimpleTokenEstimator(chars_per_token=1)
    adapter = create_adapter(
        config=AdapterConfig(adapter_type="okf"),
        bundle_id="research",
        revision="snapshot-1",
        overrides=AdapterOverrides(token_estimator=estimator),
    )
    assert isinstance(adapter, ContextAdapter)
    document = concept()
    count = adapter.estimate_tokens(document)
    source = await adapter.adapt(document, TokenBudget(max_tokens=count, reserved_for_output=0), priority=10)
    assert source.content == document.render()
    assert source.token_count == len(document.render())
    assert source.metadata["bundle_revision"] == "snapshot-1"
    assert source.metadata["content_hash"] == document.content_hash
    assert source.key == "okf:research:concept"
    assert not source.compressible
    with pytest.raises(ValueError, match="budget"):
        await adapter.adapt(document, TokenBudget(max_tokens=count - 1, reserved_for_output=0))
    with pytest.raises(TypeError):
        adapter.estimate_tokens("raw string")


def test_catalog_pagination_and_multiline_yaml() -> None:
    bundle = OKFBundle(tuple(concept(f"concept-{index:03}.md") for index in range(120)))
    first_page = bundle.catalog()
    second_page = bundle.catalog(offset=50)
    assert first_page.count("\n- ") == 50
    assert "Next catalog offset: 50" in first_page
    assert "concept-049.md" in first_page and "concept-050.md" not in first_page
    assert "concept-050.md" in second_page and "concept-049.md" not in second_page
    assert "Next catalog offset:" not in bundle.catalog(offset=100)
    doc = OKFDocument.parse(path="concept.md", text="---\ntype: Note\ncustom: |\n  ---\n---\nBody")
    assert doc.frontmatter["custom"] == "---\n"
    assert doc.body == "Body"


def test_attested_computation_is_data_and_survives_proposal() -> None:
    doc = concept(
        type="Attested Computation",
        runtime="python",
        computation="references/calculate.py",
        executor={"resource": "references/run.md", "receipt": ["result"]},
        attester={"resource": "references/check.py"},
    )
    reloaded = OKFDocument.parse(path=doc.path, text=doc.render())
    assert reloaded.frontmatter == doc.frontmatter
    proposal = reloaded.propose(body="Clarified contract", actor="cemaf/test", run_id="r1")
    assert proposal.frontmatter["executor"] == doc.frontmatter["executor"]
    assert proposal.frontmatter["attester"] == doc.frontmatter["attester"]
