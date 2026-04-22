"""OpenSpec workspace — atomic writes, per-change locks, FS layout."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

from cemaf.mcp.bridges.openspec.protocols import OpenSpecChange


class OpenSpecWorkspace:
    """Owns the `openspec/` directory layout.

    Writes land atomically under `changes/<change_id>/` via a staging dir and
    `os.replace`. Per-change asyncio locks serialize concurrent writers in the
    same process; an fcntl advisory lock on `.cemaf.lock` serializes across
    processes.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "changes").mkdir(parents=True, exist_ok=True)
        (self._root / "specs").mkdir(parents=True, exist_ok=True)
        (self._root / ".staging").mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def changes_dir(self) -> Path:
        return self._root / "changes"

    @property
    def specs_dir(self) -> Path:
        return self._root / "specs"

    def change_path(self, change_id: str) -> Path:
        return self.changes_dir / change_id

    async def _lock_for(self, change_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            return self._locks.setdefault(change_id, asyncio.Lock())

    async def write_change(
        self,
        *,
        change_id: str,
        files: Mapping[str, str],
    ) -> OpenSpecChange:
        """Write a change atomically. Replaces any existing change with the same id."""
        _validate_change_id(change_id=change_id)
        lock = await self._lock_for(change_id)
        async with lock:
            with _process_lock(self._root / ".cemaf.lock"):
                staging = await asyncio.to_thread(
                    tempfile.mkdtemp,
                    prefix=f"{change_id}-",
                    dir=str(self._root / ".staging"),
                )
                try:
                    await asyncio.to_thread(_write_files, Path(staging), files)
                    final = self.change_path(change_id)
                    if final.exists():
                        await asyncio.to_thread(shutil.rmtree, final)
                    await asyncio.to_thread(os.replace, staging, str(final))
                except Exception:
                    with contextlib.suppress(FileNotFoundError):
                        await asyncio.to_thread(shutil.rmtree, staging)
                    raise
                return OpenSpecChange(
                    change_id=change_id,
                    root=final,
                    files=tuple(sorted(files.keys())),
                )

    async def read_change(self, change_id: str) -> OpenSpecChange | None:
        _validate_change_id(change_id=change_id)
        path = self.change_path(change_id)
        if not path.exists():
            return None
        files = tuple(sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()))
        return OpenSpecChange(change_id=change_id, root=path, files=files)

    async def list_changes(self) -> tuple[str, ...]:
        if not self.changes_dir.exists():
            return ()
        entries = [p.name for p in self.changes_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        return tuple(sorted(entries))

    async def delete_change(self, change_id: str) -> bool:
        _validate_change_id(change_id=change_id)
        lock = await self._lock_for(change_id)
        async with lock:
            path = self.change_path(change_id)
            if not path.exists():
                return False
            await asyncio.to_thread(shutil.rmtree, path)
            return True


def _validate_change_id(*, change_id: str) -> None:
    if not change_id or "/" in change_id or ".." in change_id or change_id.startswith("."):
        raise ValueError(f"Invalid change_id: {change_id!r}")


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for rel_path, content in files.items():
        if ".." in Path(rel_path).parts:
            raise ValueError(f"Refusing to write outside staging: {rel_path}")
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


@contextlib.contextmanager
def _process_lock(lock_file: Path) -> Iterator[None]:
    """Advisory flock on a process-wide lock file."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
