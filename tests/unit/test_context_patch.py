"""Tests for context patch system."""

from cemaf.context.context import Context
from cemaf.context.patch import (
    ContextPatch,
    PatchLog,
    PatchOperation,
    PatchSource,
    SecurityLevel,
)


class TestContextPatch:
    """Tests for ContextPatch."""

    def test_create_set_patch(self) -> None:
        """Test creating a SET patch."""
        patch = ContextPatch.set(
            path="user.name",
            value="Alice",
            source=PatchSource.USER,
            source_id="input",
            reason="User provided name",
        )

        assert patch.path == "user.name"
        assert patch.operation == PatchOperation.SET
        assert patch.value == "Alice"
        assert patch.source == PatchSource.USER
        assert patch.source_id == "input"
        assert patch.reason == "User provided name"
        assert patch.id.startswith("patch_")

    def test_create_delete_patch(self) -> None:
        """Test creating a DELETE patch."""
        patch = ContextPatch.delete(
            path="user.temp_data",
            source=PatchSource.SYSTEM,
            reason="Cleanup",
        )

        assert patch.path == "user.temp_data"
        assert patch.operation == PatchOperation.DELETE
        assert patch.value is None

    def test_create_merge_patch(self) -> None:
        """Test creating a MERGE patch."""
        patch = ContextPatch.merge(
            path="config",
            value={"debug": True, "level": 2},
            source=PatchSource.SYSTEM,
        )

        assert patch.path == "config"
        assert patch.operation == PatchOperation.MERGE
        assert patch.value == {"debug": True, "level": 2}

    def test_create_append_patch(self) -> None:
        """Test creating an APPEND patch."""
        patch = ContextPatch.append(
            path="messages",
            value={"role": "user", "content": "Hello"},
            source=PatchSource.USER,
        )

        assert patch.path == "messages"
        assert patch.operation == PatchOperation.APPEND

    def test_from_tool(self) -> None:
        """Test creating patch from tool."""
        patch = ContextPatch.from_tool(
            tool_id="web_search",
            path="search_results",
            value=[{"title": "Result 1"}],
        )

        assert patch.source == PatchSource.TOOL
        assert patch.source_id == "web_search"
        assert "web_search" in patch.reason

    def test_from_tool_with_custom_reason(self) -> None:
        """Test creating patch from tool with custom reason."""
        patch = ContextPatch.from_tool(
            tool_id="web_search",
            path="search_results",
            value=[{"title": "Result 1"}],
            reason="Custom reason",
        )

        assert patch.reason == "Custom reason"

    def test_from_agent(self) -> None:
        """Test creating patch from agent."""
        patch = ContextPatch.from_agent(
            agent_id="research_agent",
            path="findings",
            value={"summary": "..."},
        )

        assert patch.source == PatchSource.AGENT
        assert patch.source_id == "research_agent"

    def test_serialization(self) -> None:
        """Test patch serialization."""
        patch = ContextPatch.set(
            path="test.key",
            value={"nested": "value"},
            source=PatchSource.TOOL,
            source_id="test_tool",
            correlation_id="corr-123",
        )

        data = patch.to_dict()
        restored = ContextPatch.from_dict(data)

        assert restored.path == patch.path
        assert restored.operation == patch.operation
        assert restored.value == patch.value
        assert restored.source == patch.source
        assert restored.source_id == patch.source_id
        assert restored.correlation_id == patch.correlation_id


class TestSecurityLevel:
    """SPEC-11 §3 — security classification on ContextPatch (additive, backward-compatible)."""

    def test_rank_ordering(self) -> None:
        """PUBLIC < INTERNAL < CONFIDENTIAL by rank."""
        assert SecurityLevel.PUBLIC.rank < SecurityLevel.INTERNAL.rank
        assert SecurityLevel.INTERNAL.rank < SecurityLevel.CONFIDENTIAL.rank

    def test_default_is_internal(self) -> None:
        """Inv 1 — a patch created without security_level defaults to INTERNAL."""
        patch = ContextPatch.set(path="a.b", value=1)
        assert patch.security_level is SecurityLevel.INTERNAL

    def test_explicit_level_preserved(self) -> None:
        """Factory classmethods accept and preserve an explicit level."""
        patch = ContextPatch.set(path="secret.key", value="x", security_level=SecurityLevel.CONFIDENTIAL)
        assert patch.security_level is SecurityLevel.CONFIDENTIAL

    def test_serialization_round_trip(self) -> None:
        """to_dict/from_dict preserves an explicit level."""
        patch = ContextPatch.set(path="s", value=1, security_level=SecurityLevel.CONFIDENTIAL)
        restored = ContextPatch.from_dict(patch.to_dict())
        assert restored.security_level is SecurityLevel.CONFIDENTIAL

    def test_legacy_record_without_field_defaults_internal(self) -> None:
        """Inv 2 — a serialized record lacking 'security_level' loads as INTERNAL, no error.

        Capture-don't-invent: build the real to_dict() shape then drop the field, so this
        fixture mirrors exactly what a pre-SPEC-11 checkpoint serialized.
        """
        legacy = ContextPatch.set(
            path="a.b", value=7, source=PatchSource.TOOL, source_id="old_tool"
        ).to_dict()
        del legacy["security_level"]  # simulate an old record written before the field existed

        restored = ContextPatch.from_dict(legacy)
        assert restored.security_level is SecurityLevel.INTERNAL
        # re-serialize cleanly
        assert restored.to_dict()["security_level"] == "internal"

    def test_from_agent_accepts_level(self) -> None:
        """from_agent threads the level through."""
        patch = ContextPatch.from_agent(
            agent_id="researcher",
            path="draft.body",
            value="...",
            security_level=SecurityLevel.PUBLIC,
        )
        assert patch.security_level is SecurityLevel.PUBLIC


class TestPatchLog:
    """Tests for PatchLog."""

    def test_empty_log(self) -> None:
        """Test empty patch log."""
        log = PatchLog()

        assert len(log) == 0
        assert list(log) == []

    def test_append(self) -> None:
        """Test appending patches."""
        log = PatchLog()
        patch1 = ContextPatch.set("a", 1)
        patch2 = ContextPatch.set("b", 2)

        log = log.append(patch1)
        log = log.append(patch2)

        assert len(log) == 2
        assert log[0] == patch1
        assert log[1] == patch2

    def test_extend(self) -> None:
        """Test extending with multiple patches."""
        log = PatchLog()
        patches = [
            ContextPatch.set("a", 1),
            ContextPatch.set("b", 2),
        ]

        log = log.extend(patches)

        assert len(log) == 2

    def test_replay(self) -> None:
        """Test replaying patches on context."""
        log = PatchLog()
        log = log.append(ContextPatch.set("user.name", "Alice"))
        log = log.append(ContextPatch.set("user.age", 30))
        log = log.append(ContextPatch.set("config.debug", True))

        initial = Context()
        final = log.replay(initial)

        assert final.get("user.name") == "Alice"
        assert final.get("user.age") == 30
        assert final.get("config.debug") is True

    def test_filter_by_source(self) -> None:
        """Test filtering patches by source."""
        log = PatchLog()
        log = log.append(ContextPatch.set("a", 1, source=PatchSource.TOOL))
        log = log.append(ContextPatch.set("b", 2, source=PatchSource.USER))
        log = log.append(ContextPatch.set("c", 3, source=PatchSource.TOOL))

        tool_patches = log.filter_by_source(PatchSource.TOOL)

        assert len(tool_patches) == 2
        assert all(p.source == PatchSource.TOOL for p in tool_patches)

    def test_filter_by_source_id(self) -> None:
        """Test filtering patches by source ID."""
        log = PatchLog()
        log = log.append(ContextPatch.set("a", 1, source_id="tool1"))
        log = log.append(ContextPatch.set("b", 2, source_id="tool2"))
        log = log.append(ContextPatch.set("c", 3, source_id="tool1"))

        filtered = log.filter_by_source_id("tool1")

        assert len(filtered) == 2

    def test_filter_by_path_prefix(self) -> None:
        """Test filtering patches by path prefix."""
        log = PatchLog()
        log = log.append(ContextPatch.set("user.name", "Alice"))
        log = log.append(ContextPatch.set("user.age", 30))
        log = log.append(ContextPatch.set("config.debug", True))

        user_patches = log.filter_by_path_prefix("user")

        assert len(user_patches) == 2

    def test_get_affected_paths(self) -> None:
        """Test getting affected paths."""
        log = PatchLog()
        log = log.append(ContextPatch.set("a", 1))
        log = log.append(ContextPatch.set("b", 2))
        log = log.append(ContextPatch.set("a", 3))  # Duplicate path

        paths = log.get_affected_paths()

        assert paths == {"a", "b"}

    def test_get_latest_for_path(self) -> None:
        """Test getting latest patch for a path."""
        log = PatchLog()
        log = log.append(ContextPatch.set("a", 1))
        log = log.append(ContextPatch.set("a", 2))
        log = log.append(ContextPatch.set("a", 3))

        latest = log.get_latest_for_path("a")

        assert latest is not None
        assert latest.value == 3

    def test_serialization(self) -> None:
        """Test log serialization."""
        log = PatchLog()
        log = log.append(ContextPatch.set("a", 1))
        log = log.append(ContextPatch.set("b", {"nested": True}))

        data = log.to_list()
        restored = PatchLog.from_list(data)

        assert len(restored) == 2
        assert restored[0].path == "a"
        assert restored[1].value == {"nested": True}


class TestContextApply:
    """Tests for Context.apply() method."""

    def test_apply_set(self) -> None:
        """Test applying SET patch."""
        ctx = Context()
        patch = ContextPatch.set("user.name", "Alice")

        result = ctx.apply(patch)

        assert result.get("user.name") == "Alice"

    def test_apply_delete(self) -> None:
        """Test applying DELETE patch."""
        ctx = Context(data={"user": {"name": "Alice", "age": 30}})
        patch = ContextPatch.delete("user.age")

        result = ctx.apply(patch)

        assert result.get("user.name") == "Alice"
        assert result.get("user.age") is None

    def test_apply_merge(self) -> None:
        """Test applying MERGE patch."""
        ctx = Context(data={"config": {"debug": False}})
        patch = ContextPatch.merge("config", {"level": 2, "debug": True})

        result = ctx.apply(patch)

        assert result.get("config.debug") is True
        assert result.get("config.level") == 2

    def test_apply_append(self) -> None:
        """Test applying APPEND patch."""
        ctx = Context(data={"items": [1, 2]})
        patch = ContextPatch.append("items", 3)

        result = ctx.apply(patch)

        assert result.get("items") == [1, 2, 3]


class TestContextDiff:
    """Tests for Context.diff() method."""

    def test_diff_added_key(self) -> None:
        """Test diff when key is added."""
        old = Context()
        new = Context(data={"name": "Alice"})

        patches = old.diff(new)

        assert len(patches) == 1
        assert patches[0].operation == PatchOperation.SET
        assert patches[0].path == "name"
        assert patches[0].value == "Alice"

    def test_diff_removed_key(self) -> None:
        """Test diff when key is removed."""
        old = Context(data={"name": "Alice"})
        new = Context()

        patches = old.diff(new)

        assert len(patches) == 1
        assert patches[0].operation == PatchOperation.DELETE
        assert patches[0].path == "name"

    def test_diff_modified_value(self) -> None:
        """Test diff when value is modified."""
        old = Context(data={"count": 1})
        new = Context(data={"count": 2})

        patches = old.diff(new)

        assert len(patches) == 1
        assert patches[0].operation == PatchOperation.SET
        assert patches[0].path == "count"
        assert patches[0].value == 2

    def test_diff_nested(self) -> None:
        """Test diff with nested changes."""
        old = Context(data={"user": {"name": "Alice", "age": 30}})
        new = Context(data={"user": {"name": "Alice", "age": 31}})

        patches = old.diff(new)

        assert len(patches) == 1
        assert patches[0].path == "user.age"
        assert patches[0].value == 31

    def test_diff_no_changes(self) -> None:
        """Test diff when there are no changes."""
        ctx = Context(data={"a": 1})
        patches = ctx.diff(ctx)

        assert len(patches) == 0
