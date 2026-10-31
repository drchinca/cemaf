"""Bidirectional OKF exchange through the existing DocSource protocol."""

from __future__ import annotations

import hashlib
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cemaf.docs_api.index import DocEntry, DocEntryKind
from cemaf.docs_api.protocols import DocSource
from cemaf.knowledge.okf import OKFBundle, OKFDocument

CEMAF_OKF_PROFILE_VERSION = "1.0"
_PROFILE = {"id": "cemaf", "version": CEMAF_OKF_PROFILE_VERSION, "resource": "/ontology/cemaf.md"}
_KINDS = {
    DocEntryKind.GUIDE: "Guide",
    DocEntryKind.PACKAGE: "Module",
    DocEntryKind.MODULE: "Module",
    DocEntryKind.PATTERN: "Pattern",
    DocEntryKind.SPEC: "Specification",
}
_TYPE_DEFINITIONS = {
    "Guide": "Human- and agent-readable guidance.",
    "Module": "A Python package or module and its documented responsibilities.",
    "Protocol": "A structural integration contract; implementations need not inherit it.",
    "Pattern": "A reusable composition convention.",
    "Specification": "A declared requirement or contract.",
    "Agent": "An agent declaration or explicitly registered agent interface.",
    "Skill": "A reusable procedure declaration or registered skill interface.",
    "Tool": "A tool declaration or registered callable schema, including safety metadata.",
    "Capability": "A named selector capability and the candidates in a registry snapshot.",
    "Principal": "A selected identity described by a mapping provider.",
    "Role": "A role referenced by a mapping provider; permissions remain runtime-owned.",
    "Access Policy": "A descriptive grant with scope, actions, and optional ABAC conditions.",
    "Governance Procedure": "A documented review, approval, or operational procedure.",
    "Ontology": "A versioned application vocabulary; not an inference engine.",
}


def _label(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def okf_entry_path(entry_id: str) -> str:
    """Deterministic portable path without trusting entry IDs as filesystem paths."""
    slug = re.sub(r"[^a-z0-9]+", "-", entry_id.lower()).strip("-")[:100] or "entry"
    digest = hashlib.sha256(entry_id.encode()).hexdigest()[:16]
    prefix = (
        "guides"
        if entry_id.startswith("docs/")
        else entry_id.partition(":")[0]
        if ":" in entry_id
        else "entries"
    )
    category = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")[:32] or "entries"
    return f"concepts/{category}/{slug}-{digest}.md"


def _indexes(documents: list[OKFDocument], *, page_size: int = 40) -> dict[str, bytes]:
    """Generate reserved Markdown indexes with bounded immediate-child listings."""
    groups: dict[str, list[OKFDocument]] = {}
    for doc in documents:
        groups.setdefault(posixpath.dirname(doc.path), []).append(doc)
    files = {
        "index.md": (
            b'---\nokf_version: "0.2"\n---\n# CEMAF knowledge\n\n'
            b"- [Vocabulary](ontology/cemaf.md)\n- [Concept categories](concepts/index.md)\n"
        ),
    }
    categories = "# Concept categories\n\n"
    for directory, members in sorted(groups.items()):
        label = directory.removeprefix("concepts/")
        categories += f"- [{_label(label)}]({label}/index.md)\n"
        listing = f"# {_label(label)}\n\n"
        pages = [members[start : start + page_size] for start in range(0, len(members), page_size)]
        for number, page in enumerate(pages, 1):
            index_path = (
                f"{directory}/index.md" if len(pages) == 1 else f"{directory}/pages/{number:03}/index.md"
            )
            content = f"# {_label(label)} — page {number}\n\n"
            for doc in page:
                target = posixpath.relpath(doc.path, posixpath.dirname(index_path))
                content += f"- [{_label(doc.title)}]({target})\n"
            files[index_path] = content.encode()
            if len(pages) > 1:
                listing += f"- [Page {number}](pages/{number:03}/index.md)\n"
        if len(pages) > 1:
            files[f"{directory}/index.md"] = listing.encode()
    files["concepts/index.md"] = categories.encode()
    return files


def _related_section(links: list[str]) -> str:
    if not links:
        return ""
    return "\n\n## Related concepts\n\n" + "\n".join(
        f"- [{_label(value)}](/{okf_entry_path(value)})" for value in links
    )


def _markdown_references(entry: DocEntry, paths: dict[Path, str]) -> set[str]:
    """Connect known documentation targets while preserving original prose."""
    if entry.kind != DocEntryKind.GUIDE or not entry.path.endswith(".md"):
        return set()
    document = OKFDocument(path="source.md", frontmatter={"type": "Guide"}, body=entry.body)
    related = set()
    for link in document.links():
        try:
            parsed = urlsplit(link)
        except ValueError:
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (Path(entry.path).parent / unquote(parsed.path)).resolve()
        if target in paths and paths[target] != entry.id:
            related.add(paths[target])
    return related


def build_okf_bundle(*, sources: Iterable[DocSource]) -> OKFBundle:
    """Export any structural DocSource; fail on duplicate identities.

    This serializes descriptions, not executable registrations or access grants.
    Security-sensitive sources must be wrapped in GovernedDocSource before use.
    """
    entries: dict[str, DocEntry] = {}
    for source in sources:
        for entry in source.load():
            if entry.id in entries:
                raise ValueError(f"Duplicate documentation entry: {entry.id}")
            entries[entry.id] = entry
    documents = []
    paths = {
        Path(entry.path).resolve(): entry.id
        for entry in entries.values()
        if entry.kind == DocEntryKind.GUIDE and entry.path.endswith(".md")
    }
    for key, entry in sorted(entries.items()):
        concept_type = entry.metadata.get("okf_type", _KINDS[entry.kind])
        related = entry.metadata.get("related_ids", [])
        related = related if isinstance(related, (list, tuple)) else []
        # Only explicit cross-references to exported concepts become new links.
        # Original Markdown is retained; its other links can remain unresolved.
        links = sorted(
            {value for value in related if isinstance(value, str) and value in entries}
            | _markdown_references(entry, paths)
        )
        body = entry.body + _related_section(links)
        documents.append(
            OKFDocument(
                path=okf_entry_path(key),
                frontmatter={
                    "type": concept_type,
                    "title": entry.title,
                    "description": str(entry.metadata.get("description", entry.title)),
                    "resource": f"cemaf:{key}",
                    "cemaf_profile": dict(_PROFILE),
                    "cemaf_entry": {
                        "id": key,
                        "kind": entry.kind.value,
                        "source": entry.source,
                        "anchors": list(entry.anchors),
                        "related_exported_ids": links,
                        "metadata": {
                            **{k: v for k, v in entry.metadata.items() if k != "okf"},
                            "related_ids": links,
                        },
                    },
                },
                body=body,
            )
        )
    types = sorted({doc.type for doc in documents})
    documents.append(
        OKFDocument(
            path="ontology/cemaf.md",
            frontmatter={
                "type": "Ontology",
                "title": "CEMAF knowledge vocabulary",
                "cemaf_profile": dict(_PROFILE),
                "concept_types": types,
                "type_definitions": dict(_TYPE_DEFINITIONS),
                "relation_types": ["references", "extracted_from"],
            },
            body=(
                "# CEMAF knowledge vocabulary\n\n"
                "This is a CEMAF application profile, not a standard OKF ontology.\n\n"
                "Each concept describes one guide, module, protocol, agent, skill, tool, capability, "
                "policy, principal, role, or governance procedure. Unknown types remain valid.\n\n"
                "`cemaf_entry` preserves the DocSource identity, kind, anchors, and metadata. "
                "`related_ids` names other entries; exported references are ordinary Markdown links. "
                "A capability declaration does not prove runtime availability. Policy descriptions "
                "do not grant access, and skill descriptions do not register executable code.\n\n"
                "`okf_version` versions the file format; `cemaf_profile.version` versions this "
                "vocabulary convention. Git commits/tags version bundle history; the bundle's "
                "content hash pins exact bytes. No ontology inference or migration engine is implied.\n"
            ),
        )
    )
    return OKFBundle(tuple(documents), _indexes(documents[:-1]))


@dataclass(frozen=True)
class OKFDocSource:
    """Load an OKF snapshot into DocIndex, existing docs tools, or docs MCP."""

    bundle: OKFBundle
    bundle_id: str

    @property
    def name(self) -> str:
        return "okf"

    def load(self) -> Iterable[DocEntry]:
        revision = self.bundle.revision
        seen: set[str] = set()
        for document in self.bundle.documents:
            identity = document.frontmatter.get("cemaf_entry", {})
            identity = identity if isinstance(identity, dict) else {}
            entry_id = str(identity.get("id") or document.source_id(bundle_id=self.bundle_id))
            if entry_id in seen:
                raise ValueError(f"Duplicate OKF documentation identity: {entry_id}")
            seen.add(entry_id)
            try:
                kind = DocEntryKind(identity.get("kind", "guide"))
            except ValueError:
                kind = DocEntryKind.GUIDE
            metadata = identity.get("metadata", {})
            anchors = identity.get("anchors", [])
            anchors = anchors if isinstance(anchors, (list, tuple)) else []
            related = identity.get("related_exported_ids", [])
            related = (
                related if isinstance(related, list) and all(isinstance(x, str) for x in related) else []
            )
            suffix = _related_section(related)
            body = document.body.removesuffix(suffix) if suffix else document.body
            yield DocEntry(
                id=entry_id,
                kind=kind,
                title=document.title,
                body=body,
                source=str(identity.get("source") or self.name),
                path=document.path,
                anchors=tuple(value for value in anchors if isinstance(value, str)),
                metadata={
                    **(metadata if isinstance(metadata, dict) else {}),
                    "okf": document.metadata(bundle_id=self.bundle_id, revision=revision),
                },
            )
