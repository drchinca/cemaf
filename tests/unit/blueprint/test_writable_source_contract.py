"""Contract tests for `WritableBlueprintSource`.

These are protocol-shape tests — no behavior, just the structural-typing
contract. They lock in the invariants that (a) writable sources still
pass `BlueprintSource`, (b) read-only sources do NOT pass
`WritableBlueprintSource`, and (c) the protocol is `@runtime_checkable`
so `isinstance` works without inheritance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.blueprint import (
    BlueprintSource,
    InMemoryBlueprintSource,
    InMemoryWritableBlueprintSource,
    JSONFileBlueprintSource,
    SqliteBlueprintSource,
    WritableBlueprintSource,
)


class TestWritableSourceContract:
    def test_in_memory_writable_conforms(self) -> None:
        source = InMemoryWritableBlueprintSource()
        assert isinstance(source, WritableBlueprintSource)
        # And still a BlueprintSource (read capability preserved).
        assert isinstance(source, BlueprintSource)

    def test_sqlite_source_conforms(self, tmp_path: Path) -> None:
        source = SqliteBlueprintSource(db_path=str(tmp_path / "bp.db"))
        assert isinstance(source, WritableBlueprintSource)
        assert isinstance(source, BlueprintSource)

    def test_read_only_in_memory_is_not_writable(self) -> None:
        source = InMemoryBlueprintSource(entries=())
        assert isinstance(source, BlueprintSource)
        # No `append` / `close` — must NOT pass the writable contract.
        assert not isinstance(source, WritableBlueprintSource)

    def test_read_only_json_file_is_not_writable(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text("[]")
        source = JSONFileBlueprintSource(path=path)
        assert isinstance(source, BlueprintSource)
        assert not isinstance(source, WritableBlueprintSource)

    def test_plain_object_is_not_writable(self) -> None:
        class Impostor:
            name = "fake"

        assert not isinstance(Impostor(), WritableBlueprintSource)

    @pytest.mark.asyncio
    async def test_close_is_idempotent_on_in_memory(self) -> None:
        source = InMemoryWritableBlueprintSource()
        await source.close()
        await source.close()  # second call must not raise
