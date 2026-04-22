"""DocSource implementations — markdown files and Python docstrings."""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Iterable
from pathlib import Path

from cemaf.docs_api.index import DocEntry, DocEntryKind

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", flags=re.MULTILINE)
_SECTION_SPLIT_RE = re.compile(r"^(#{2,3})\s+.+?$", flags=re.MULTILINE)


class MarkdownDocSource:
    """Load markdown files from `docs/**/*.md` as DocEntry records.

    Each top-level .md file becomes one GUIDE entry. If the file is
    `docs/patterns.md`, its `## N. …` sections are additionally exploded
    into PATTERN entries so individual patterns are directly addressable.
    """

    def __init__(self, *, root: Path) -> None:
        self._root = Path(root)

    @property
    def name(self) -> str:
        return "markdown"

    def load(self) -> Iterable[DocEntry]:
        if not self._root.exists():
            return
        for md_path in sorted(self._root.rglob("*.md")):
            body = md_path.read_text(encoding="utf-8")
            rel = md_path.relative_to(self._root)
            entry_id = f"docs/{rel.as_posix()}"
            title = _extract_title(body=body) or md_path.stem
            anchors = tuple(heading for _level, heading in _HEADING_RE.findall(body))
            yield DocEntry(
                id=entry_id,
                kind=DocEntryKind.GUIDE,
                title=title,
                body=body,
                source=self.name,
                path=str(md_path),
                anchors=anchors,
                metadata={"relative_path": rel.as_posix()},
            )

            # Explode patterns.md sections into PATTERN entries
            if rel.name == "patterns.md":
                yield from _patterns_sections(body=body, md_path=md_path)


def _patterns_sections(*, body: str, md_path: Path) -> Iterable[DocEntry]:
    """Yield one PATTERN entry per `## N. …` section in patterns.md."""
    lines = body.splitlines(keepends=True)
    current_title: str | None = None
    current_buffer: list[str] = []
    current_anchor: str = ""

    def _flush() -> DocEntry | None:
        if current_title is None:
            return None
        section_body = "".join(current_buffer).strip()
        if not section_body:
            return None
        return DocEntry(
            id=f"pattern:{current_anchor}",
            kind=DocEntryKind.PATTERN,
            title=current_title,
            body=section_body,
            source="markdown",
            path=str(md_path),
            anchors=(current_title,),
            metadata={"origin": "docs/patterns.md"},
        )

    for line in lines:
        match = re.match(r"^##\s+(\d+)\.\s+(.+?)\s*$", line)
        if match is not None:
            if (flushed := _flush()) is not None:
                yield flushed
            num, heading = match.group(1), match.group(2)
            current_title = f"{num}. {heading}"
            current_anchor = f"{num}-{_slugify(heading)}"
            current_buffer = [line]
        elif current_title is not None:
            current_buffer.append(line)
    if (flushed := _flush()) is not None:
        yield flushed


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or "section"


def _extract_title(*, body: str) -> str | None:
    for match in _HEADING_RE.finditer(body):
        level, heading = match.group(1), match.group(2)
        if len(level) == 1:
            return heading
    return None


class PackageDocstringSource:
    """Reflect over `cemaf.*` and yield package + module docstrings.

    Package entries (DocEntryKind.PACKAGE) come from `<pkg>.__init__.py`.
    Module entries (DocEntryKind.MODULE) come from key module docstrings
    under each package. We keep the reflection conservative — only
    packages named under `cemaf` are traversed, and we skip private modules
    (leading underscore) to avoid internal-only detail.
    """

    def __init__(self, *, root_package: str = "cemaf") -> None:
        self._root_package = root_package

    @property
    def name(self) -> str:
        return "docstring"

    def load(self) -> Iterable[DocEntry]:
        try:
            root = importlib.import_module(self._root_package)
        except ImportError:
            return

        # Yield the root package doc if present
        if root.__doc__:
            yield _package_entry(name=self._root_package, doc=root.__doc__)

        root_path = getattr(root, "__path__", None)
        if root_path is None:
            return

        for module_info in pkgutil.walk_packages(root_path, prefix=f"{self._root_package}."):
            if "._" in module_info.name or module_info.name.endswith("._"):
                continue
            try:
                module = importlib.import_module(module_info.name)
            except Exception:
                # A broken/optional module (missing extra) shouldn't break the index.
                continue
            doc = getattr(module, "__doc__", None)
            if not doc or not doc.strip():
                continue
            if module_info.ispkg:
                yield _package_entry(name=module_info.name, doc=doc)
            else:
                yield _module_entry(name=module_info.name, doc=doc)


def _package_entry(*, name: str, doc: str) -> DocEntry:
    first_line = doc.strip().splitlines()[0] if doc.strip() else name
    return DocEntry(
        id=f"pkg:{name}",
        kind=DocEntryKind.PACKAGE,
        title=f"{name} — {first_line}",
        body=doc.strip(),
        source="docstring",
        path=name,
        anchors=(name,),
        metadata={"module": name},
    )


def _module_entry(*, name: str, doc: str) -> DocEntry:
    first_line = doc.strip().splitlines()[0] if doc.strip() else name
    return DocEntry(
        id=f"mod:{name}",
        kind=DocEntryKind.MODULE,
        title=f"{name} — {first_line}",
        body=doc.strip(),
        source="docstring",
        path=name,
        anchors=(name,),
        metadata={"module": name},
    )
