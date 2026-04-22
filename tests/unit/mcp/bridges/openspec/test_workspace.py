"""Tests for OpenSpecWorkspace — atomic writes, locks, FS layout."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace


def test_workspace_creates_expected_directories(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    assert (tmp_path / "openspec").is_dir()
    assert ws.changes_dir.is_dir()
    assert ws.specs_dir.is_dir()
    assert (tmp_path / "openspec" / ".staging").is_dir()


@pytest.mark.asyncio
async def test_write_and_read_change_roundtrip(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    change = await ws.write_change(
        change_id="add-feature-x",
        files={
            "proposal.md": "# Why\nBecause.\n",
            "tasks.md": "- [ ] step 1\n",
            "specs/feature-x/spec.md": "## ADDED Requirements\n### Requirement: X\n#### Scenario: S\n",
        },
    )
    assert change.change_id == "add-feature-x"
    assert set(change.files) == {"proposal.md", "tasks.md", "specs/feature-x/spec.md"}
    reread = await ws.read_change(change_id="add-feature-x")
    assert reread is not None
    assert (reread.root / "proposal.md").read_text() == "# Why\nBecause.\n"


@pytest.mark.asyncio
async def test_write_overwrites_existing_change_atomically(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    await ws.write_change(change_id="c1", files={"proposal.md": "v1\n"})
    await ws.write_change(change_id="c1", files={"proposal.md": "v2\n", "tasks.md": "t\n"})
    change = await ws.read_change(change_id="c1")
    assert change is not None
    assert (change.root / "proposal.md").read_text() == "v2\n"
    assert (change.root / "tasks.md").read_text() == "t\n"


@pytest.mark.asyncio
async def test_list_changes_returns_sorted_ids(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    await ws.write_change(change_id="c2", files={"proposal.md": "x"})
    await ws.write_change(change_id="c1", files={"proposal.md": "x"})
    assert await ws.list_changes() == ("c1", "c2")


@pytest.mark.asyncio
async def test_delete_change_removes_directory(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    await ws.write_change(change_id="to-delete", files={"proposal.md": "x"})
    deleted = await ws.delete_change(change_id="to-delete")
    assert deleted is True
    assert await ws.read_change(change_id="to-delete") is None


@pytest.mark.asyncio
async def test_delete_missing_change_returns_false(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    assert await ws.delete_change(change_id="nope") is False


@pytest.mark.asyncio
async def test_read_missing_change_returns_none(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    assert await ws.read_change(change_id="nope") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["", "../escape", "a/b", ".hidden"])
async def test_invalid_change_id_raises(tmp_path: Path, bad_id: str) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    with pytest.raises(ValueError):
        await ws.write_change(change_id=bad_id, files={"proposal.md": "x"})


@pytest.mark.asyncio
async def test_path_traversal_in_file_key_rejected(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")
    with pytest.raises(ValueError):
        await ws.write_change(change_id="c1", files={"../outside.md": "escape"})


@pytest.mark.asyncio
async def test_concurrent_writes_same_change_are_serialized(tmp_path: Path) -> None:
    ws = OpenSpecWorkspace(root=tmp_path / "openspec")

    async def writer(version: str) -> None:
        await ws.write_change(change_id="race", files={"proposal.md": f"v={version}\n"})

    await asyncio.gather(*(writer(str(i)) for i in range(10)))
    change = await ws.read_change(change_id="race")
    assert change is not None
    content = (change.root / "proposal.md").read_text()
    assert content.startswith("v=")
