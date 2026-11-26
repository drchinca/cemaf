"""Protocol-first exchange of framework knowledge and governance descriptions."""

from pathlib import Path

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.docs_api import DocEntry, DocEntryKind, DocIndex, DocSource, OKFDocSource, build_okf_bundle
from cemaf.docs_api.contracts import PythonContractDocSource
from cemaf.docs_api.okf import okf_entry_path
from cemaf.knowledge import OKFBundle
from cemaf.security.mappings import DictMappingProvider
from cemaf.security.okf import GovernanceDocSource, GovernedDocSource
from cemaf.security.rbac import RBACEnforcer, ScopeAuthorizer


class CustomSource:
    name = "custom"

    def load(self) -> tuple[DocEntry, ...]:
        return (
            DocEntry(
                id="governance:review",
                kind=DocEntryKind.GUIDE,
                title="Review procedure",
                body="A human reviews each proposed policy change.",
                source=self.name,
                anchors=("Review",),
                metadata={"okf_type": "Governance Procedure", "related_ids": ["protocol:policy"]},
            ),
            DocEntry(
                id="protocol:policy",
                kind=DocEntryKind.SPEC,
                title="Policy protocol",
                body="Implement the policy protocol structurally.",
                source=self.name,
                metadata={"okf_type": "Protocol"},
            ),
        )


def test_structural_sources_export_and_return_to_docs_index(tmp_path: Path) -> None:
    source = CustomSource()
    assert isinstance(source, DocSource)
    bundle = build_okf_bundle(sources=(source,))
    doc = bundle.get(okf_entry_path("governance:review")[:-3])
    assert doc.type == "Governance Procedure"
    assert doc.frontmatter["cemaf_profile"]["version"] == "1.0"
    assert f"/{okf_entry_path('protocol:policy')}" in doc.links()
    ontology = bundle.get("ontology/cemaf")
    assert ontology.frontmatter["concept_types"] == ["Governance Procedure", "Protocol"]
    assert b'okf_version: "0.2"' in bundle.supporting_files["index.md"]
    restored_source = OKFDocSource(bundle=OKFBundle.load(bundle.write(tmp_path / "bundle")), bundle_id="test")
    assert isinstance(restored_source, DocSource)
    index = DocIndex()
    index.add_from(sources=(restored_source,))
    restored = index.get("governance:review")
    assert restored is not None
    assert restored.body == source.load()[0].body
    assert restored.anchors == ("Review",)
    assert restored.metadata["okf"]["bundle_revision"] == bundle.revision
    assert index.search(query="policy protocol", k=2)
    # Importing descriptions must not convert them to runtime registrations.
    assert restored.metadata["okf"]["trust_tier"] == "unverified"


def test_export_rejects_duplicate_ids_and_portable_paths() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        build_okf_bundle(sources=(CustomSource(), CustomSource()))
    assert ".." not in okf_entry_path("../../outside.md")
    assert okf_entry_path("a:b") != okf_entry_path("a/b")


def test_plain_file_indexes_are_small_and_resolve(tmp_path: Path) -> None:
    import posixpath

    from cemaf.knowledge import OKFDocument

    class ManyModules:
        name = "modules"

        def load(self):
            return (
                DocEntry(
                    id=f"module:sample.{i}",
                    kind=DocEntryKind.MODULE,
                    title=f"Module {i}",
                    body="Public contract.",
                )
                for i in range(125)
            )

    bundle = build_okf_bundle(sources=(ManyModules(),))
    bundle.write(tmp_path / "bundle")
    assert bundle.supporting_files["index.md"].count(b"\n- ") == 2
    assert bundle.supporting_files["concepts/module/index.md"].count(b"\n- ") == 4
    paths = {doc.path for doc in bundle.documents} | bundle.supporting_files.keys()
    targets = set()
    for path, data in bundle.supporting_files.items():
        assert data.count(b"\n- ") <= 40
        parser = OKFDocument(path="links.md", frontmatter={"type": "Index"}, body=data.decode())
        for href in parser.links():
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), href))
            assert target in paths
            targets.add(target)
    assert {doc.path for doc in bundle.documents} <= targets


def test_markdown_source_links_become_portable_graph_edges(tmp_path: Path) -> None:
    from cemaf.docs_api import MarkdownDocSource

    (tmp_path / "first.md").write_text("# First\n\nSee [second](second.md#details).\n")
    (tmp_path / "second.md").write_text("# Second\n\n## Details\n\nA protocol description.")
    bundle = build_okf_bundle(sources=(MarkdownDocSource(root=tmp_path),))
    first = bundle.get(okf_entry_path("docs/first.md")[:-3])
    assert f"/{okf_entry_path('docs/second.md')}" in first.links()
    restored = next(entry for entry in OKFDocSource(bundle, "docs").load() if entry.id == "docs/first.md")
    assert restored.body == (tmp_path / "first.md").read_text()
    assert restored.metadata["related_ids"] == ["docs/second.md"]


def test_contract_source_is_static_and_covers_protocols_and_skills(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text('"""Example package."""\n')
    (tmp_path / "contracts.py").write_text('''"""Contracts for the example."""
raise RuntimeError("Must not import source code")
from typing import Protocol, runtime_checkable
import example
@runtime_checkable
class Store(Protocol):
    async def read(self, key: str) -> str: ...
class Work(Skill[Input, Output]):
    def execute(self, value): ...
''')
    source = PythonContractDocSource(root=tmp_path, package="example")
    assert isinstance(source, DocSource)
    entries = {entry.id: entry for entry in source.load()}
    contract = entries["contract:example.contracts.Store"]
    assert contract.metadata["okf_type"] == "Protocol"
    assert contract.metadata["runtime_checkable"]
    assert "async read(self, key: str) -> str" in contract.body
    assert entries["contract:example.contracts.Work"].metadata["okf_type"] == "Skill"
    assert entries["module:example.contracts"].metadata["related_ids"] == ["module:example"]


def _mapping() -> dict:
    return {
        "users": {
            "curator": {
                "roles": [],
                "attributes": {"department": "research"},
                "direct_access": [
                    {
                        "scope": "project",
                        "scope_path_prefix": "/governance/",
                        "actions": ["read"],
                        "abac_conditions": {"department": "research"},
                    }
                ],
            },
            "reader": {"roles": ["READER"]},
            "outsider": {
                "roles": [],
                "attributes": {"department": "other"},
                "direct_access": [
                    {
                        "scope": "project",
                        "scope_path_prefix": "/governance/",
                        "actions": ["read"],
                        "abac_conditions": {"department": "research"},
                    }
                ],
            },
        }
    }


def test_rbac_abac_governed_export_and_revocation() -> None:
    mapping = _mapping()
    provider = DictMappingProvider(mapping)
    authorizer = RBACEnforcer(provider)
    assert isinstance(authorizer, ScopeAuthorizer)
    source = GovernanceDocSource(provider=provider, principal_ids=("curator", "reader"))
    entries = tuple(source.load())
    assert {entry.metadata["okf_type"] for entry in entries} == {"Principal", "Role", "Access Policy"}
    bindings = {entry.id: (MemoryScope.PROJECT, "/governance/" + entry.id) for entry in entries}
    governed = GovernedDocSource(source, authorizer, "curator", bindings)
    assert isinstance(governed, DocSource)
    bundle = build_okf_bundle(sources=(governed,))
    grant = bundle.get(okf_entry_path("grant:curator:0")[:-3])
    assert grant.frontmatter["cemaf_entry"]["metadata"]["abac_conditions"] == {"department": "research"}
    # Role-based reader and attribute-qualified curator both pass the existing enforcer.
    assert tuple(GovernedDocSource(source, authorizer, "reader", bindings).load())
    with pytest.raises(PermissionError, match="disclosure denied"):
        build_okf_bundle(sources=(GovernedDocSource(source, authorizer, "outsider", bindings),))
    mapping["users"]["curator"]["attributes"]["department"] = "other"
    with pytest.raises(PermissionError):
        build_okf_bundle(sources=(governed,))


def test_missing_binding_and_metadata_forgery_do_not_grant_access() -> None:
    provider = DictMappingProvider(_mapping())
    source = CustomSource()
    with pytest.raises(PermissionError):
        tuple(GovernedDocSource(source, RBACEnforcer(provider), "reader", {}).load())
    bindings = {entry.id: (MemoryScope.PROJECT, "/outside/") for entry in source.load()}
    with pytest.raises(PermissionError):
        tuple(GovernedDocSource(source, RBACEnforcer(provider), "curator", bindings).load())

    class CustomPolicy:
        def can(self, principal_id, action, scope, scope_path=None):
            return principal_id == "custom" and action == "read"

    assert isinstance(CustomPolicy(), ScopeAuthorizer)
    assert tuple(GovernedDocSource(source, CustomPolicy(), "custom", bindings).load())
