"""Unit tests for `SqliteBlueprintSource` — round-trip + concurrency + lifecycle."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.library import BlueprintEntry, BlueprintEntryKind
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource


@pytest.fixture
def tiny_blueprint() -> Blueprint:
    return Blueprint(
        id="tiny",
        name="Tiny",
        scene_goal=SceneGoal(objective="x"),
        style_guide=StyleGuide(tone="neutral"),
    )


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "bp.db")


class TestSqliteRoundTrip:
    @pytest.mark.asyncio
    async def test_roundtrip_snapshot_kind(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        entry = BlueprintEntry.snapshot_entry(id="s1", title="S1", blueprint=tiny_blueprint)
        await source.append(entry=entry)
        await source.close()

        reopened = SqliteBlueprintSource(db_path=_db(tmp_path))
        loaded = list(reopened.load())
        assert len(loaded) == 1
        got = loaded[0]
        assert got.id == "s1"
        assert got.kind is BlueprintEntryKind.SNAPSHOT
        # JSON round-trip turns tuples → lists; the real contract is that the
        # snapshot still parses back into the original Blueprint via Pydantic.
        assert got.snapshot is not None
        assert Blueprint.from_dict(data=got.snapshot) == tiny_blueprint

    @pytest.mark.asyncio
    async def test_roundtrip_factory_kind(self, tmp_path: Path) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        entry = BlueprintEntry.factory_entry(
            id="f1",
            title="F1",
            factory_ref="pkg.mod:fn",
        )
        await source.append(entry=entry)
        await source.close()

        reopened = SqliteBlueprintSource(db_path=_db(tmp_path))
        loaded = list(reopened.load())
        assert len(loaded) == 1
        got = loaded[0]
        assert got.kind is BlueprintEntryKind.FACTORY
        assert got.factory_ref == "pkg.mod:fn"

    @pytest.mark.asyncio
    async def test_roundtrip_recipe_kind(self, tmp_path: Path) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        recipe = {"name": "R1", "goal": "do the thing"}
        entry = BlueprintEntry.recipe_entry(id="r1", title="R1", recipe=recipe)
        await source.append(entry=entry)
        await source.close()

        reopened = SqliteBlueprintSource(db_path=_db(tmp_path))
        loaded = list(reopened.load())
        assert len(loaded) == 1
        got = loaded[0]
        assert got.kind is BlueprintEntryKind.RECIPE
        assert got.recipe == recipe

    @pytest.mark.asyncio
    async def test_scope_fields_round_trip(self, tmp_path: Path) -> None:
        """SPEC-13 — project_id/confidence/scope survive durable persistence.

        Regression guard: these fields were added to BlueprintEntry but the SQLite schema
        didn't persist them, so a project-scoped harvested blueprint reloaded as unscoped —
        silently breaking promotion. This pins the round-trip at the source level.
        """
        from cemaf.blueprint.core import BlueprintScope

        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        entry = BlueprintEntry.recipe_entry(
            id="harvest/alpha/abc123",
            title="scoped",
            recipe={"goal": "g"},
            project_id="alpha",
            confidence=0.87,
            scope=BlueprintScope.PROJECT,
        )
        await source.append(entry=entry)
        await source.close()

        got = next(iter(SqliteBlueprintSource(db_path=_db(tmp_path)).load()))
        assert got.project_id == "alpha"
        assert got.confidence == pytest.approx(0.87)
        assert got.scope is BlueprintScope.PROJECT

    @pytest.mark.asyncio
    async def test_legacy_table_without_scope_columns_migrates(self, tmp_path: Path) -> None:
        """A pre-SPEC-13 blueprint_entries table (no scope columns) loads with defaults."""
        import sqlite3

        db = _db(tmp_path)
        # Hand-build the OLD schema (11 columns, no project_id/confidence/scope) + one row.
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE blueprint_entries (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "title TEXT NOT NULL, description TEXT NOT NULL, tags_json TEXT NOT NULL, "
            "source TEXT NOT NULL, path TEXT NOT NULL, version TEXT NOT NULL, "
            "payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO blueprint_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "old1",
                "recipe",
                "Old",
                "",
                "[]",
                "legacy",
                "",
                "1.0",
                '{"goal": "g"}',
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        # load() runs the additive migration → the legacy row gets the column defaults.
        from cemaf.blueprint.core import BlueprintScope

        got = next(iter(SqliteBlueprintSource(db_path=db).load()))
        assert got.id == "old1"
        assert got.project_id == ""
        assert got.confidence == 0.5
        assert got.scope is BlueprintScope.PROJECT

    @pytest.mark.asyncio
    async def test_migration_errors_other_than_duplicate_columns_fail_loudly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        tiny_blueprint: Blueprint,
    ) -> None:
        import sqlite3

        from cemaf.blueprint import sqlite_source

        monkeypatch.setattr(
            sqlite_source,
            "_MIGRATIONS",
            ("ALTER TABLE blueprint_entries ADD COLUMN",),
        )
        source = SqliteBlueprintSource(db_path=_db(tmp_path))

        with pytest.raises(sqlite3.OperationalError):
            await source.append(
                entry=BlueprintEntry.snapshot_entry(
                    id="s1",
                    title="S1",
                    blueprint=tiny_blueprint,
                )
            )

    @pytest.mark.asyncio
    async def test_tags_description_metadata_preserved(
        self, tmp_path: Path, tiny_blueprint: Blueprint
    ) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        entry = BlueprintEntry.snapshot_entry(
            id="x",
            title="X",
            blueprint=tiny_blueprint,
            description="desc",
            tags=("a", "b"),
        )
        await source.append(entry=entry)
        await source.close()

        loaded = list(SqliteBlueprintSource(db_path=_db(tmp_path)).load())[0]
        assert loaded.description == "desc"
        assert loaded.tags == ("a", "b")

    @pytest.mark.asyncio
    async def test_source_name_stamped_when_missing(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        db = _db(tmp_path)
        source = SqliteBlueprintSource(db_path=db, name="curated-catalog")
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)
        assert entry.source == ""  # harvester default
        await source.append(entry=entry)
        await source.close()

        loaded = list(SqliteBlueprintSource(db_path=db).load())[0]
        assert loaded.source == "curated-catalog"

    @pytest.mark.asyncio
    async def test_source_name_respected_when_explicit(
        self, tmp_path: Path, tiny_blueprint: Blueprint
    ) -> None:
        db = _db(tmp_path)
        source = SqliteBlueprintSource(db_path=db, name="curated-catalog")
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint, source="explicit")
        await source.append(entry=entry)
        await source.close()

        loaded = list(SqliteBlueprintSource(db_path=db).load())[0]
        assert loaded.source == "explicit"


class TestSqliteUpsertSemantics:
    @pytest.mark.asyncio
    async def test_append_same_id_replaces(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        await source.append(
            entry=BlueprintEntry.snapshot_entry(id="x", title="First", blueprint=tiny_blueprint)
        )
        await source.append(
            entry=BlueprintEntry.snapshot_entry(id="x", title="Second", blueprint=tiny_blueprint)
        )
        await source.close()

        loaded = list(SqliteBlueprintSource(db_path=_db(tmp_path)).load())
        assert len(loaded) == 1
        assert loaded[0].title == "Second"


class TestSqliteConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_appends_serialize(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        try:

            async def _write(i: int) -> None:
                await source.append(
                    entry=BlueprintEntry.snapshot_entry(
                        id=f"bp-{i:02d}",
                        title=f"BP {i}",
                        blueprint=tiny_blueprint,
                    )
                )

            await asyncio.gather(*(_write(i) for i in range(20)))
        finally:
            await source.close()

        loaded = list(SqliteBlueprintSource(db_path=_db(tmp_path)).load())
        ids = {entry.id for entry in loaded}
        assert len(ids) == 20
        assert ids == {f"bp-{i:02d}" for i in range(20)}


class TestSqliteConcurrentReaderWriter:
    @pytest.mark.asyncio
    async def test_load_during_active_writer_succeeds(
        self, tmp_path: Path, tiny_blueprint: Blueprint
    ) -> None:
        """Sync `load()` sets busy_timeout — concurrent writer must not cause SQLITE_BUSY.

        Under WAL, readers don't block writers and vice versa, but schema
        statements (CREATE IF NOT EXISTS) briefly take a write lock. Without
        `busy_timeout` on the sync reader's connection, a tight race where
        the aiosqlite writer holds the lock causes `OperationalError: database
        is locked`. With `busy_timeout`, the reader retries for up to 5s.
        """
        db = _db(tmp_path)
        writer = SqliteBlueprintSource(db_path=db)

        async def _hammer_writes() -> None:
            for i in range(20):
                await writer.append(
                    entry=BlueprintEntry.snapshot_entry(
                        id=f"bp-{i:02d}",
                        title=f"BP {i}",
                        blueprint=tiny_blueprint,
                    ),
                )

        async def _hammer_reads() -> int:
            total = 0
            for _ in range(5):
                # Each load() opens a fresh sync connection — exactly the
                # pattern that would clash with the writer without busy_timeout.
                reader = SqliteBlueprintSource(db_path=db)
                total += len(list(reader.load()))
                await asyncio.sleep(0)
            return total

        write_task = asyncio.create_task(_hammer_writes())
        read_task = asyncio.create_task(_hammer_reads())
        await write_task
        total_reads = await read_task
        await writer.close()

        # No SQLITE_BUSY raised; final write count correct.
        assert len(list(SqliteBlueprintSource(db_path=db).load())) == 20
        assert total_reads >= 0  # readers completed without raising


class TestSqliteLifecycle:
    @pytest.mark.asyncio
    async def test_load_empty_when_file_new(self, tmp_path: Path) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        # Never appended anything — load() returns empty iterator.
        assert list(source.load()) == []

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, tmp_path: Path) -> None:
        source = SqliteBlueprintSource(db_path=_db(tmp_path))
        await source.close()
        await source.close()  # second call must not raise

    @pytest.mark.asyncio
    async def test_reopen_sees_prior_writes(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        db = _db(tmp_path)
        s1 = SqliteBlueprintSource(db_path=db)
        await s1.append(
            entry=BlueprintEntry.snapshot_entry(id="persist", title="P", blueprint=tiny_blueprint)
        )
        await s1.close()

        s2 = SqliteBlueprintSource(db_path=db)
        loaded = list(s2.load())
        assert len(loaded) == 1
        assert loaded[0].id == "persist"
