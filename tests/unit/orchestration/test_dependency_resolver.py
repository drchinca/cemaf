"""
Tests for Dependency Resolver.

Ensures regex-based context chaining works correctly.
"""

from cemaf.context.context import Context
from cemaf.orchestration.dependency_resolver import resolve_dependencies, resolve_node_input


class TestDependencyResolver:
    """Tests for dependency resolution."""

    def test_resolve_simple_placeholder(self):
        """Test resolving a simple placeholder."""
        context = Context(data={"STEP_1_OUTPUT": "blueprint_json"})
        input_params = {"blueprint": "$$STEP_1_OUTPUT$$"}

        resolved = resolve_dependencies(input_params, context)

        assert resolved["blueprint"] == "blueprint_json"

    def test_resolve_embedded_placeholder(self):
        """Test resolving placeholder embedded in text."""
        context = Context(data={"STEP_1_OUTPUT": "blueprint_json"})
        input_params = {"blueprint": "Use this: $$STEP_1_OUTPUT$$ for generation"}

        resolved = resolve_dependencies(input_params, context)

        assert "blueprint_json" in resolved["blueprint"]
        assert "$$STEP_1_OUTPUT$$" not in resolved["blueprint"]

    def test_resolve_multiple_placeholders(self):
        """Test resolving multiple placeholders."""
        context = Context(
            data={
                "STEP_1_OUTPUT": "blueprint",
                "STEP_2_OUTPUT": "facts",
            }
        )
        input_params = {
            "blueprint": "$$STEP_1_OUTPUT$$",
            "facts": "$$STEP_2_OUTPUT$$",
        }

        resolved = resolve_dependencies(input_params, context)

        assert resolved["blueprint"] == "blueprint"
        assert resolved["facts"] == "facts"

    def test_resolve_nested_dict(self):
        """Test resolving placeholders in nested dictionaries."""
        context = Context(data={"STEP_1_OUTPUT": "value"})
        input_params = {
            "nested": {
                "key": "$$STEP_1_OUTPUT$$",
            }
        }

        resolved = resolve_dependencies(input_params, context)

        assert resolved["nested"]["key"] == "value"

    def test_resolve_list(self):
        """Test resolving placeholders in lists."""
        context = Context(data={"STEP_1_OUTPUT": "value"})
        input_params = {
            "items": ["$$STEP_1_OUTPUT$$", "static"],
        }

        resolved = resolve_dependencies(input_params, context)

        assert resolved["items"][0] == "value"
        assert resolved["items"][1] == "static"

    def test_resolve_missing_placeholder(self):
        """Missing placeholder resolves to None — lets Pydantic defaults kick in.

        Before: kept the raw $$STEP_1_OUTPUT$$ string which would then fail
        Pydantic validation on downstream goal construction. None is the
        signal to _build_goal to use the field's default value.
        """
        context = Context(data={})
        input_params = {"blueprint": "$$STEP_1_OUTPUT$$"}

        resolved = resolve_dependencies(input_params, context)

        assert resolved["blueprint"] is None

    def test_resolve_no_placeholders(self):
        """Test resolving input with no placeholders."""
        context = Context(data={"STEP_1_OUTPUT": "value"})
        input_params = {"blueprint": "static_value"}

        resolved = resolve_dependencies(input_params, context)

        assert resolved["blueprint"] == "static_value"

    def test_resolve_complex_nested_structure(self):
        """Test resolving complex nested structures."""
        context = Context(
            data={
                "STEP_1_OUTPUT": "blueprint",
                "STEP_2_OUTPUT": "facts",
            }
        )
        input_params = {
            "config": {
                "blueprint": "$$STEP_1_OUTPUT$$",
                "nested": {
                    "facts": "$$STEP_2_OUTPUT$$",
                    "list": ["$$STEP_1_OUTPUT$$", "static"],
                },
            }
        }

        resolved = resolve_dependencies(input_params, context)

        assert resolved["config"]["blueprint"] == "blueprint"
        assert resolved["config"]["nested"]["facts"] == "facts"
        assert resolved["config"]["nested"]["list"][0] == "blueprint"
        assert resolved["config"]["nested"]["list"][1] == "static"

    def test_resolve_node_input_convenience(self):
        """Test resolve_node_input convenience function."""
        context = Context(data={"STEP_1_OUTPUT": "value"})
        input_mapping = {"key": "$$STEP_1_OUTPUT$$"}

        resolved = resolve_node_input(input_mapping, context)

        assert resolved["key"] == "value"

    def test_resolve_preserves_non_string_values(self):
        """Test that non-string values are preserved."""
        context = Context(data={"STEP_1_OUTPUT": {"nested": "object"}})
        input_params = {"blueprint": "$$STEP_1_OUTPUT$$"}

        resolved = resolve_dependencies(input_params, context)

        # When placeholder is exact match, should return raw object
        assert isinstance(resolved["blueprint"], dict)
        assert resolved["blueprint"]["nested"] == "object"
