"""Tests for sandbox snapshot and restore."""

import pytest

from cemaf.sandbox.shell import NetworkPolicy, ShellSandbox, ShellSandboxConfig
from cemaf.sandbox.snapshot import compare_manifests, restore, snapshot


@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapshot_and_restore_round_trip(tmp_path) -> None:
    root = tmp_path / "workspace"
    sandbox = ShellSandbox(config=ShellSandboxConfig(root=root, network=NetworkPolicy.ALLOW))
    await sandbox.setup()

    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    manifest, blob_store = snapshot(sandbox, blob_store=tmp_path / "blobs")
    assert any(entry.path == "src/main.py" for entry in manifest.files)

    (root / "src" / "main.py").write_text("print('changed')\n", encoding="utf-8")
    restore(sandbox, manifest=manifest, blob_store=blob_store)
    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('ok')\n"


@pytest.mark.unit
def test_compare_manifests_detects_changes() -> None:
    from cemaf.sandbox.snapshot import SandboxFileEntry, SandboxManifest

    left = SandboxManifest(
        root="/tmp/a",
        files=(SandboxFileEntry(path="a.py", sha256="abc", size_bytes=3),),
    )
    right = SandboxManifest(
        root="/tmp/a",
        files=(SandboxFileEntry(path="a.py", sha256="def", size_bytes=3),),
    )
    identical, diffs = compare_manifests(expected=left, actual=right)
    assert not identical
    assert any("changed: a.py" in diff for diff in diffs)
