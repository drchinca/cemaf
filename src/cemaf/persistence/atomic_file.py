"""Crash-safe local file replacement and cross-process advisory locking."""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def process_file_lock(path: str | Path) -> Iterator[None]:
    """Serialize cooperating processes with a POSIX advisory file lock."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write_text(
    path: str | Path,
    data: str,
    *,
    encoding: str = "utf-8",
    keep_backup: bool = True,
) -> None:
    """Durably replace a text file without exposing a partial target.

    The new payload is flushed to a same-directory temporary file before an
    atomic ``os.replace``. When replacing an existing file, ``.bak`` receives
    an independently flushed copy first so readers can recover from external
    corruption as well as an interrupted writer.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    new_temp: Path | None = _write_temp(
        target=target,
        data=data,
        encoding=encoding,
        suffix=".new",
    )
    backup_temp: Path | None = None
    try:
        if keep_backup and target.is_file():
            backup_temp = _copy_temp(target=target, suffix=".bak.tmp")
            os.replace(backup_temp, target.with_suffix(target.suffix + ".bak"))
            backup_temp = None
        assert new_temp is not None
        os.replace(new_temp, target)
        new_temp = None
        _fsync_directory(target.parent)
    finally:
        if new_temp is not None:
            new_temp.unlink(missing_ok=True)
        if backup_temp is not None:
            backup_temp.unlink(missing_ok=True)


def read_text_with_backup(path: str | Path, *, encoding: str = "utf-8") -> str:
    """Read the primary file, falling back to its last-good ``.bak`` copy."""
    target = Path(path)
    try:
        return target.read_text(encoding=encoding)
    except (OSError, UnicodeError):
        return target.with_suffix(target.suffix + ".bak").read_text(encoding=encoding)


def _write_temp(*, target: Path, data: str, encoding: str, suffix: str) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=suffix, dir=target.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _copy_temp(*, target: Path, suffix: str) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=suffix, dir=target.parent)
    os.close(fd)
    temp_path = Path(raw_path)
    try:
        shutil.copyfile(target, temp_path)
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _fsync_directory(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
