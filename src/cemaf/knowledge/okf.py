"""Portable Open Knowledge Format documents and filesystem bundle snapshots.

Requires ``cemaf[okf]``. Optional dependencies are loaded only when used.
Knowledge remains ordinary Markdown; no code or resource URL is executed.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.retrieval.protocols import Document

_RESERVED = {"index.md", "log.md"}


def _yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("OKF support requires: pip install 'cemaf[okf]'") from exc
    return yaml


def _path(value: str) -> str:
    """Validate portable bundle paths before any filesystem operation."""
    path = PurePosixPath(value)
    if (
        not value
        or value == "."
        or value != path.as_posix()
        or path.is_absolute()
        or any(part in {"..", ".git"} for part in path.parts)
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ValueError(f"Invalid OKF bundle path: {value!r}")
    return value


def _frontmatter(text: str) -> tuple[JSON, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("OKF concepts require YAML frontmatter")
    for index, line in enumerate(lines[1:], 1):
        if line.rstrip("\r\n") == "---":
            yaml = _yaml()
            try:
                metadata = yaml.safe_load("".join(lines[1:index]))
            except yaml.YAMLError as exc:
                raise ValueError(f"Invalid OKF frontmatter: {exc}") from exc
            if not isinstance(metadata, dict):
                raise ValueError("OKF frontmatter must be a mapping")
            return metadata, "".join(lines[index + 1 :])
    raise ValueError("Unclosed OKF frontmatter")


def _json_metadata(metadata: JSON) -> JSON:
    # YAML timestamps and extension scalars must survive JSON-backed stores.
    # The source document retains their original YAML representation.
    return dict(json.loads(json.dumps(metadata, default=str)))


def _instant(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime) and value.utcoffset() is not None:
        return value
    return None


@dataclass(frozen=True)
class OKFDocument:
    """One concept; its ID is the bundle path without the ``.md`` suffix.

    Unknown types and frontmatter fields are retained. Unedited parsed
    documents render byte-for-byte as text, including YAML comments.
    """

    path: str
    frontmatter: JSON
    body: str
    _original: str | None = field(default=None, repr=False, compare=False)
    _original_metadata: JSON | None = field(default=None, repr=False, compare=False)
    _original_body: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _path(self.path)
        path = PurePosixPath(self.path)
        if path.suffix != ".md" or path.name in _RESERVED:
            raise ValueError("OKF concepts need a non-reserved .md filename")
        concept_type = self.frontmatter.get("type")
        if not isinstance(concept_type, str) or not concept_type.strip():
            raise ValueError(f"{self.path}: OKF type must be a non-empty string")
        object.__setattr__(self, "frontmatter", deepcopy(self.frontmatter))

    @classmethod
    def parse(cls, *, path: str, text: str) -> OKFDocument:
        """Parse a UTF-8 Markdown concept without imposing a domain taxonomy."""
        metadata, body = _frontmatter(text)
        return cls(path, metadata, body, text, deepcopy(metadata), body)

    @property
    def concept_id(self) -> str:
        return self.path[:-3]

    @property
    def type(self) -> str:
        return str(self.frontmatter["type"])

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title") or PurePosixPath(self.path).stem)

    @property
    def trust_tier(self) -> str:
        """Derive advisory OKF v0.2 trust; this is not authorization."""
        verified = self.frontmatter.get("verified", [])
        if isinstance(verified, dict):
            verified = [verified]
        if not isinstance(verified, list):
            return "unverified"
        actors = [item.get("by") for item in verified if isinstance(item, dict)]
        actor_names = [actor for actor in actors if isinstance(actor, str) and actor]
        if any(actor.startswith("human:") for actor in actor_names):
            return "human-reviewed"
        return "machine-confirmed" if actor_names else "unverified"

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status", "stable"))

    def is_stale(self, *, now: datetime | None = None) -> bool:
        if now is not None and now.utcoffset() is None:
            raise ValueError("Staleness comparisons require an explicit UTC offset")
        instant = _instant(self.frontmatter.get("stale_after"))
        return instant is not None and (now or utc_now()) >= instant

    def render(self) -> str:
        """Serialize all metadata, preserving unchanged source formatting."""
        if (
            self._original is not None
            and self.frontmatter == self._original_metadata
            and self.body == self._original_body
        ):
            return self._original
        header = _yaml().safe_dump(self.frontmatter, sort_keys=False, allow_unicode=True)
        return f"---\n{header}---\n{self.body}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()

    def source_id(self, *, bundle_id: str) -> str:
        """Namespace concept identities without tying them to a local path."""
        if not bundle_id or ":" in bundle_id:
            raise ValueError("bundle_id must be non-empty and contain no colon")
        return f"okf:{bundle_id}:{self.concept_id}"

    def metadata(self, *, bundle_id: str, revision: str = "") -> JSON:
        """JSON-compatible evidence for retrieval, context, and graph stores."""
        return {
            "format": "okf",
            "source_type": "okf",
            "bundle_id": bundle_id,
            "bundle_revision": revision,
            "concept_id": self.concept_id,
            "path": self.path,
            "content_hash": self.content_hash,
            "title": self.title,
            "okf_type": self.type,
            "trust_tier": self.trust_tier,
            "status": self.status,
            "frontmatter": _json_metadata(self.frontmatter),
        }

    def to_document(self, *, bundle_id: str, revision: str = "") -> Document:
        """Project into CEMAF retrieval, retaining evidence for citations."""
        return Document(
            id=self.source_id(bundle_id=bundle_id),
            content=self.render(),
            metadata=self.metadata(bundle_id=bundle_id, revision=revision),
        )

    def propose(self, *, body: str, actor: str, run_id: str, now: datetime | None = None) -> OKFDocument:
        """Create an unverified draft tied to its base content and CEMAF run.

        This does not write or ratify anything. Old verification is removed
        because it describes the previous content, not the proposed revision.
        """
        if not actor.strip() or not run_id.strip():
            raise ValueError("Proposals require an actor and run_id")
        timestamp = now or utc_now()
        if timestamp.utcoffset() is None:
            raise ValueError("Proposal timestamps require an explicit UTC offset")
        metadata = deepcopy(self.frontmatter)
        metadata.pop("verified", None)
        metadata["status"] = "draft"
        metadata["generated"] = {"by": actor, "at": timestamp.isoformat()}
        metadata["cemaf_proposal"] = {"run_id": run_id, "base_content_hash": self.content_hash}
        return OKFDocument(path=self.path, frontmatter=metadata, body=body)

    def proposal_matches(self, current: OKFDocument) -> bool:
        """Check a proposal's base before review; this does not approve changes.

        Both identity and exact source bytes must match. Missing/malformed
        proposal evidence returns False, including an ordinary source document.
        """
        proposal = self.frontmatter.get("cemaf_proposal")
        return (
            self.path == current.path
            and isinstance(proposal, dict)
            and proposal.get("base_content_hash") == current.content_hash
            and isinstance(proposal.get("run_id"), str)
            and bool(proposal["run_id"].strip())
        )

    def links(self) -> tuple[str, ...]:
        """CommonMark link destinations, excluding images and code examples."""
        try:
            from markdown_it import MarkdownIt
        except ImportError as exc:
            raise ImportError("OKF links require: pip install 'cemaf[okf]'") from exc
        destinations = []
        for token in MarkdownIt("commonmark").parse(self.body):
            for child in token.children or []:
                if child.type == "link_open":
                    href = child.attrGet("href")
                    if isinstance(href, str):
                        destinations.append(href)
        return tuple(dict.fromkeys(destinations))

    def resolve_link(self, href: str) -> str | None:
        """Return a local concept ID; external and escaping links stay opaque."""
        try:
            parsed = urlsplit(href)
        except ValueError:
            return None
        if parsed.scheme or parsed.netloc:
            return None
        path = unquote(parsed.path)
        if not path:
            return self.concept_id if parsed.fragment else None
        resolved = posixpath.normpath(
            path.lstrip("/") if path.startswith("/") else posixpath.join(posixpath.dirname(self.path), path)
        )
        try:
            _path(resolved)
        except ValueError:
            return None
        if not resolved.endswith(".md") or PurePosixPath(resolved).name in _RESERVED:
            return None
        return resolved[:-3]


@dataclass(frozen=True)
class OKFBundleDiff:
    """Changes from one portable bundle snapshot to another.

    Concept fields contain IDs without .md; supporting fields contain paths.
    Moves are represented as removal plus addition. No backend is mutated.
    """

    before_revision: str
    after_revision: str
    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    supporting_added: tuple[str, ...] = ()
    supporting_modified: tuple[str, ...] = ()
    supporting_removed: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.added,
                self.modified,
                self.removed,
                self.supporting_added,
                self.supporting_modified,
                self.supporting_removed,
            )
        )


@dataclass(frozen=True)
class OKFBundle:
    """An offline snapshot, including index/log files and supporting assets.

    Export creates a new directory. Git history and review are owned by the
    consuming application; CEMAF never merges proposals automatically.
    """

    documents: tuple[OKFDocument, ...]
    supporting_files: dict[str, bytes] = field(default_factory=dict, repr=False)
    _root: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(self, "supporting_files", dict(self.supporting_files))
        paths = [doc.path for doc in self.documents]
        if len(set(paths)) != len(paths):
            raise ValueError("Duplicate OKF concept paths")
        for name in self.supporting_files:
            _path(name)
            if name in paths or (name.endswith(".md") and PurePosixPath(name).name not in _RESERVED):
                raise ValueError(f"Supporting file overlaps an OKF concept: {name}")
        all_paths = set(paths) | self.supporting_files.keys()
        for name in all_paths:
            if any(parent.as_posix() in all_paths for parent in PurePosixPath(name).parents):
                raise ValueError(f"OKF file/directory collision: {name}")

    @classmethod
    def load(cls, root: str | Path) -> OKFBundle:
        """Read local files only; ignore Git internals and reject symlinks."""
        root = Path(root)
        if not root.is_dir():
            raise ValueError(f"OKF bundle is not a directory: {root}")
        documents = []
        supporting = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if ".git" in relative.parts:
                continue
            if path.is_symlink():
                raise ValueError(f"OKF bundle cannot contain symlinks: {relative}")
            if not path.is_file():
                continue
            name = relative.as_posix()
            content = path.read_bytes()
            if path.suffix == ".md" and path.name not in _RESERVED:
                documents.append(OKFDocument.parse(path=name, text=content.decode("utf-8")))
            else:
                supporting[name] = content
        return cls(documents=tuple(documents), supporting_files=supporting, _root=root.resolve())

    def get(self, concept_id: str) -> OKFDocument:
        for document in self.documents:
            if document.concept_id == concept_id:
                return document
        raise KeyError(concept_id)

    def with_document(self, document: OKFDocument) -> OKFBundle:
        """Return a new snapshot with a concept added or replaced."""
        documents = {doc.path: doc for doc in self.documents}
        documents[document.path] = document
        return OKFBundle(
            tuple(documents[key] for key in sorted(documents)), dict(self.supporting_files), self._root
        )

    def without_document(self, concept_id: str) -> OKFBundle:
        """Return a new snapshot without a concept; fail on an unknown ID."""
        self.get(concept_id)
        return OKFBundle(
            tuple(doc for doc in self.documents if doc.concept_id != concept_id),
            self.supporting_files,
            self._root,
        )

    def diff(self, previous: OKFBundle) -> OKFBundleDiff:
        """Compare exact content to support review and selective reindexing.

        This reports direct changes, not transitive invalidation. A changed
        protocol or supporting computation can require reevaluating otherwise
        unchanged findings, according to application policy.
        """
        before = {doc.concept_id: doc.content_hash for doc in previous.documents}
        after = {doc.concept_id: doc.content_hash for doc in self.documents}
        old_files, new_files = previous.supporting_files, self.supporting_files
        return OKFBundleDiff(
            before_revision=previous.revision,
            after_revision=self.revision,
            added=tuple(sorted(after.keys() - before.keys())),
            modified=tuple(sorted(key for key in before.keys() & after.keys() if before[key] != after[key])),
            removed=tuple(sorted(before.keys() - after.keys())),
            supporting_added=tuple(sorted(new_files.keys() - old_files.keys())),
            supporting_modified=tuple(
                sorted(key for key in old_files.keys() & new_files.keys() if old_files[key] != new_files[key])
            ),
            supporting_removed=tuple(sorted(old_files.keys() - new_files.keys())),
        )

    def catalog(self, directory: str = "", *, offset: int = 0, limit: int = 50) -> str:
        """Compact immediate-child discovery without loading bodies into prompts.

        Descend into a listed directory, then select concepts with ``get``.
        Only identity, type, title, and description are included. Trust and
        evidence are available when the selected concept is opened.
        """
        if offset < 0 or limit < 1:
            raise ValueError("Catalog offset must be non-negative and limit must be positive")
        entries = self.catalog_entries(directory)
        prefix = f"{directory}/" if directory else ""
        page = list(entries[offset : offset + limit])
        if offset + limit < len(entries):
            page.append(f"Next catalog offset: {offset + limit}")
        return "\n".join([f"# /{prefix}", *page])

    def catalog_entries(self, directory: str = "", *, include_descriptions: bool = True) -> tuple[str, ...]:
        """Return deterministic immediate-child summaries for budgeted discovery."""
        if directory:
            _path(directory)
        prefix = f"{directory}/" if directory else ""
        rows = []
        directories = set()
        for document in sorted(self.documents, key=lambda doc: doc.path):
            if not document.path.startswith(prefix):
                continue
            relative = document.path[len(prefix) :]
            if "/" in relative:
                directories.add(relative.split("/", 1)[0])
            else:
                # JSON strings keep multiline metadata from forging catalog rows.
                title = json.dumps(document.title, ensure_ascii=False)
                description = json.dumps(document.frontmatter.get("description", ""), ensure_ascii=False)
                concept_type = json.dumps(document.type, ensure_ascii=False)
                row = f"- /{document.path} | {concept_type} | {title}"
                rows.append(f"{row} | {description}" if include_descriptions else row)
        return (*(f"- /{prefix}{name}/" for name in sorted(directories)), *rows)

    def _files(self) -> dict[str, bytes]:
        return {**self.supporting_files, **{doc.path: doc.render().encode("utf-8") for doc in self.documents}}

    @property
    def revision(self) -> str:
        """Content-addressed snapshot identity, independent of filesystem root."""
        manifest = [(name, hashlib.sha256(data).hexdigest()) for name, data in sorted(self._files().items())]
        return hashlib.sha256(json.dumps(manifest).encode("utf-8")).hexdigest()

    def write(self, destination: str | Path) -> Path:
        """Export to a new directory, refusing any existing destination."""
        # Revalidate in case a caller mutated a supplied metadata/container dict.
        self.__post_init__()
        files = self._files()
        destination = Path(destination)
        if self._root is not None and destination.resolve().is_relative_to(self._root):
            raise ValueError("Export destination must be outside the source bundle")
        destination.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(content)
        return destination
