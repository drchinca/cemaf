"""Content-addressed snapshot and restore for shell sandboxes."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cemaf.sandbox.shell import ShellSandbox

_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".iccha",
        ".cemaf",
    }
)


@dataclass(frozen=True)
class SandboxFileEntry:
    """One file in a sandbox manifest."""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SandboxManifest:
    """Content-addressed manifest of a sandbox workspace."""

    root: str
    files: tuple[SandboxFileEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [
                {
                    "path": entry.path,
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                }
                for entry in self.files
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SandboxManifest:
        return cls(
            root=payload["root"],
            files=tuple(
                SandboxFileEntry(
                    path=item["path"],
                    sha256=item["sha256"],
                    size_bytes=item["size_bytes"],
                )
                for item in payload.get("files", [])
            ),
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(
    sandbox: ShellSandbox,
    *,
    blob_store: Path | None = None,
) -> tuple[SandboxManifest, Path]:
    """Capture a content-addressed manifest and blob store for a sandbox root."""
    root = sandbox.root.resolve()
    store = (blob_store or (root / ".cemaf" / "snapshots" / "blobs")).resolve()
    store.mkdir(parents=True, exist_ok=True)

    entries: list[SandboxFileEntry] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        digest = _sha256_file(path)
        blob_path = store / digest
        if not blob_path.exists():
            shutil.copy2(path, blob_path)
        entries.append(SandboxFileEntry(path=rel, sha256=digest, size_bytes=path.stat().st_size))

    manifest = SandboxManifest(root=str(root), files=tuple(entries))
    return manifest, store


def restore(
    sandbox: ShellSandbox,
    *,
    manifest: SandboxManifest,
    blob_store: Path,
) -> None:
    """Restore sandbox files from a manifest and content-addressed blob store."""
    root = sandbox.root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    for entry in manifest.files:
        destination = root / entry.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blob_store / entry.sha256, destination)


def compare_manifests(
    *,
    expected: SandboxManifest,
    actual: SandboxManifest,
) -> tuple[bool, list[str]]:
    """Compare two manifests; return (identical, list of human-readable diffs)."""
    expected_map = {entry.path: entry for entry in expected.files}
    actual_map = {entry.path: entry for entry in actual.files}
    diffs: list[str] = []

    for path in sorted(set(expected_map) | set(actual_map)):
        left = expected_map.get(path)
        right = actual_map.get(path)
        if left is None:
            diffs.append(f"added: {path}")
            continue
        if right is None:
            diffs.append(f"removed: {path}")
            continue
        if left.sha256 != right.sha256:
            diffs.append(f"changed: {path} ({left.sha256[:8]} -> {right.sha256[:8]})")

    return len(diffs) == 0, diffs
