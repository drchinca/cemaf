"""Tests for blueprint module."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.mock import MockBlueprintRegistry, create_mock_blueprint
from cemaf.blueprint.rules import BlueprintContentRule, BlueprintSchemaRule
from cemaf.blueprint.schema import (
    Blueprint,
    Participant,
    SceneGoal,
    StyleGuide,
)

# =============================================================================
# SceneGoal Tests
# =============================================================================


class TestSceneGoal:
    """Tests for SceneGoal model."""

    def test_required_objective(self) -> None:
        """Test objective is required."""
        goal = SceneGoal(objective="Test objective")
        assert goal.objective == "Test objective"

    def test_defaults(self) -> None:
        """Test default values."""
        goal = SceneGoal(objective="Test")
        assert goal.success_criteria == ()
        assert goal.constraints == ()
        assert goal.priority == 1

    def test_frozen(self) -> None:
        """Test model is frozen (immutable)."""
        goal = SceneGoal(objective="Test")
        with pytest.raises(PydanticValidationError):
            goal.objective = "Modified"  # type: ignore

    def test_with_all_fields(self) -> None:
        """Test creating with all fields."""
        goal = SceneGoal(
            objective="Complete the task",
            success_criteria=("Criterion 1", "Criterion 2"),
            constraints=("Constraint 1",),
            priority=2,
        )
        assert goal.objective == "Complete the task"
        assert len(goal.success_criteria) == 2
        assert len(goal.constraints) == 1
        assert goal.priority == 2


# =============================================================================
# StyleGuide Tests
# =============================================================================


class TestStyleGuide:
    """Tests for StyleGuide model."""

    def test_defaults(self) -> None:
        """Test default values."""
        style = StyleGuide()
        assert style.tone == ""
        assert style.format == ""
        assert style.length_hint == ""
        assert style.vocabulary == ()
        assert style.avoid == ()
        assert style.examples == ()

    def test_frozen(self) -> None:
        """Test model is frozen (immutable)."""
        style = StyleGuide(tone="professional")
        with pytest.raises(PydanticValidationError):
            style.tone = "casual"  # type: ignore

    def test_is_empty_true(self) -> None:
        """Test is_empty returns True for default style."""
        style = StyleGuide()
        assert style.is_empty() is True

    def test_is_empty_false(self) -> None:
        """Test is_empty returns False when any field is set."""
        style = StyleGuide(tone="casual")
        assert style.is_empty() is False

        style2 = StyleGuide(vocabulary=("term1",))
        assert style2.is_empty() is False

    def test_with_all_fields(self) -> None:
        """Test creating with all fields."""
        style = StyleGuide(
            tone="professional",
            format="markdown",
            length_hint="concise",
            vocabulary=("term1", "term2"),
            avoid=("avoid1",),
            examples=("Example output",),
        )
        assert style.tone == "professional"
        assert style.format == "markdown"
        assert len(style.vocabulary) == 2


# =============================================================================
# Participant Tests
# =============================================================================


class TestParticipant:
    """Tests for Participant model."""

    def test_required_fields(self) -> None:
        """Test name and role are required."""
        participant = Participant(name="Agent", role="Helper")
        assert participant.name == "Agent"
        assert participant.role == "Helper"

    def test_defaults(self) -> None:
        """Test default values."""
        participant = Participant(name="Agent", role="Helper")
        assert participant.traits == ()
        assert participant.voice == ""
        assert participant.constraints == ()

    def test_frozen(self) -> None:
        """Test model is frozen (immutable)."""
        participant = Participant(name="Agent", role="Helper")
        with pytest.raises(PydanticValidationError):
            participant.name = "Modified"  # type: ignore

    def test_with_all_fields(self) -> None:
        """Test creating with all fields."""
        participant = Participant(
            name="Writer",
            role="Content Writer",
            traits=("creative", "concise"),
            voice="friendly",
            constraints=("avoid jargon",),
        )
        assert participant.name == "Writer"
        assert len(participant.traits) == 2
        assert participant.voice == "friendly"


# =============================================================================
# Blueprint Tests
# =============================================================================


class TestBlueprint:
    """Tests for Blueprint model."""

    def test_required_fields(self) -> None:
        """Test required fields (id, name, scene_goal)."""
        goal = SceneGoal(objective="Test objective")
        blueprint = Blueprint(id="bp-1", name="Test Blueprint", scene_goal=goal)
        assert blueprint.id == "bp-1"
        assert blueprint.name == "Test Blueprint"
        assert blueprint.scene_goal.objective == "Test objective"

    def test_missing_id_raises(self) -> None:
        """Test missing id raises error."""
        goal = SceneGoal(objective="Test")
        with pytest.raises(PydanticValidationError):
            Blueprint(name="Test", scene_goal=goal)  # type: ignore

    def test_missing_name_raises(self) -> None:
        """Test missing name raises error."""
        goal = SceneGoal(objective="Test")
        with pytest.raises(PydanticValidationError):
            Blueprint(id="bp-1", scene_goal=goal)  # type: ignore

    def test_missing_scene_goal_raises(self) -> None:
        """Test missing scene_goal raises error."""
        with pytest.raises(PydanticValidationError):
            Blueprint(id="bp-1", name="Test")  # type: ignore

    def test_frozen(self) -> None:
        """Test model is frozen (immutable)."""
        goal = SceneGoal(objective="Test")
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal)
        with pytest.raises(PydanticValidationError):
            blueprint.name = "Modified"  # type: ignore

    def test_defaults(self) -> None:
        """Test default values."""
        goal = SceneGoal(objective="Test")
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal)
        assert blueprint.description == ""
        assert blueprint.style_guide.is_empty() is True
        assert blueprint.participants == ()
        assert blueprint.instruction == ""
        assert blueprint.version == "1.0"
        assert blueprint.tags == ()
        assert blueprint.metadata == {}

    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        goal = SceneGoal(objective="Test objective")
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal)
        data = blueprint.to_dict()

        assert data["id"] == "bp-1"
        assert data["name"] == "Test"
        assert data["scene_goal"]["objective"] == "Test objective"

    def test_from_dict(self) -> None:
        """Test from_dict creation."""
        data = {
            "id": "bp-1",
            "name": "Test",
            "scene_goal": {"objective": "Test objective"},
        }
        blueprint = Blueprint.from_dict(data)

        assert blueprint.id == "bp-1"
        assert blueprint.name == "Test"
        assert blueprint.scene_goal.objective == "Test objective"

    def test_to_dict_from_dict_roundtrip(self) -> None:
        """Test to_dict/from_dict roundtrip preserves data."""
        goal = SceneGoal(
            objective="Complete task",
            success_criteria=("Criterion 1",),
            priority=2,
        )
        style = StyleGuide(tone="professional", format="markdown")
        participant = Participant(name="Writer", role="Helper")
        original = Blueprint(
            id="bp-1",
            name="Test Blueprint",
            description="A test",
            scene_goal=goal,
            style_guide=style,
            participants=(participant,),
            instruction="Do this",
            version="2.0",
            tags=("tag1", "tag2"),
            metadata={"key": "value"},
        )

        data = original.to_dict()
        restored = Blueprint.from_dict(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.scene_goal.objective == original.scene_goal.objective
        assert restored.style_guide.tone == original.style_guide.tone
        assert len(restored.participants) == 1
        assert restored.instruction == original.instruction
        assert restored.version == original.version
        assert restored.tags == original.tags
        assert restored.metadata == original.metadata

    def test_to_prompt_basic(self) -> None:
        """Test to_prompt with basic blueprint."""
        goal = SceneGoal(objective="Test objective")
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal)
        prompt = blueprint.to_prompt()

        assert "## Goal" in prompt
        assert "Objective: Test objective" in prompt

    def test_to_prompt_with_style(self) -> None:
        """Test to_prompt includes style section when non-empty."""
        goal = SceneGoal(objective="Test objective")
        style = StyleGuide(tone="professional", format="markdown")
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal, style_guide=style)
        prompt = blueprint.to_prompt()

        assert "## Style Guide" in prompt
        assert "Tone: professional" in prompt
        assert "Format: markdown" in prompt

    def test_to_prompt_with_participants(self) -> None:
        """Test to_prompt includes participants section."""
        goal = SceneGoal(objective="Test objective")
        participant = Participant(name="Writer", role="Content Creator", traits=("creative",))
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal, participants=(participant,))
        prompt = blueprint.to_prompt()

        assert "## Participants" in prompt
        assert "### Writer" in prompt
        assert "Role: Content Creator" in prompt
        assert "Traits: creative" in prompt

    def test_to_prompt_with_instruction(self) -> None:
        """Test to_prompt includes instructions section."""
        goal = SceneGoal(objective="Test objective")
        blueprint = Blueprint(
            id="bp-1",
            name="Test",
            scene_goal=goal,
            instruction="Detailed instruction here",
        )
        prompt = blueprint.to_prompt()

        assert "## Instructions" in prompt
        assert "Detailed instruction here" in prompt

    def test_to_prompt_with_success_criteria(self) -> None:
        """Test to_prompt includes success criteria."""
        goal = SceneGoal(
            objective="Test objective",
            success_criteria=("Criterion 1", "Criterion 2"),
        )
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal)
        prompt = blueprint.to_prompt()

        assert "Success Criteria:" in prompt
        assert "- Criterion 1" in prompt
        assert "- Criterion 2" in prompt

    def test_to_prompt_with_constraints(self) -> None:
        """Test to_prompt includes constraints."""
        goal = SceneGoal(
            objective="Test objective",
            constraints=("Constraint 1",),
        )
        blueprint = Blueprint(id="bp-1", name="Test", scene_goal=goal)
        prompt = blueprint.to_prompt()

        assert "Constraints:" in prompt
        assert "- Constraint 1" in prompt


# =============================================================================
# BlueprintBuilder Tests
# =============================================================================


class TestBlueprintBuilder:
    """Tests for BlueprintBuilder."""

    def test_basic_build(self) -> None:
        """Test building a basic blueprint."""
        blueprint = BlueprintBuilder("bp-1", "Test Blueprint").with_goal("Test objective").build()

        assert blueprint.id == "bp-1"
        assert blueprint.name == "Test Blueprint"
        assert blueprint.scene_goal.objective == "Test objective"

    def test_missing_goal_raises(self) -> None:
        """Test building without goal raises ValueError."""
        builder = BlueprintBuilder("bp-1", "Test")
        with pytest.raises(ValueError, match="goal objective"):
            builder.build()

    def test_empty_id_raises(self) -> None:
        """Test empty id raises ValueError."""
        builder = BlueprintBuilder("", "Test").with_goal("Objective")
        with pytest.raises(ValueError, match="requires an id"):
            builder.build()

    def test_empty_name_raises(self) -> None:
        """Test empty name raises ValueError."""
        builder = BlueprintBuilder("bp-1", "").with_goal("Objective")
        with pytest.raises(ValueError, match="requires a name"):
            builder.build()

    def test_with_description(self) -> None:
        """Test with_description method."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test").with_description("A description").with_goal("Objective").build()
        )
        assert blueprint.description == "A description"

    def test_with_goal_full(self) -> None:
        """Test with_goal with all parameters."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test")
            .with_goal(
                objective="Test objective",
                success_criteria=["Criterion 1", "Criterion 2"],
                constraints=["Constraint 1"],
                priority=2,
            )
            .build()
        )

        assert blueprint.scene_goal.objective == "Test objective"
        assert len(blueprint.scene_goal.success_criteria) == 2
        assert len(blueprint.scene_goal.constraints) == 1
        assert blueprint.scene_goal.priority == 2

    def test_with_style(self) -> None:
        """Test with_style method."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test")
            .with_goal("Objective")
            .with_style(
                tone="professional",
                format="markdown",
                length_hint="concise",
                vocabulary=["term1"],
                avoid=["avoid1"],
                examples=["Example"],
            )
            .build()
        )

        assert blueprint.style_guide.tone == "professional"
        assert blueprint.style_guide.format == "markdown"
        assert blueprint.style_guide.length_hint == "concise"
        assert "term1" in blueprint.style_guide.vocabulary
        assert "avoid1" in blueprint.style_guide.avoid
        assert "Example" in blueprint.style_guide.examples

    def test_add_participant(self) -> None:
        """Test add_participant method."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test")
            .with_goal("Objective")
            .add_participant(
                name="Writer",
                role="Content Creator",
                traits=["creative"],
                voice="friendly",
                constraints=["no jargon"],
            )
            .build()
        )

        assert len(blueprint.participants) == 1
        assert blueprint.participants[0].name == "Writer"
        assert blueprint.participants[0].role == "Content Creator"
        assert "creative" in blueprint.participants[0].traits

    def test_add_multiple_participants(self) -> None:
        """Test adding multiple participants."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test")
            .with_goal("Objective")
            .add_participant("Writer", "Writer Role")
            .add_participant("Reviewer", "Reviewer Role")
            .build()
        )

        assert len(blueprint.participants) == 2

    def test_with_instruction(self) -> None:
        """Test with_instruction method."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test")
            .with_goal("Objective")
            .with_instruction("Detailed instructions")
            .build()
        )
        assert blueprint.instruction == "Detailed instructions"

    def test_with_version(self) -> None:
        """Test with_version method."""
        blueprint = BlueprintBuilder("bp-1", "Test").with_goal("Objective").with_version("2.0").build()
        assert blueprint.version == "2.0"

    def test_with_tags(self) -> None:
        """Test with_tags method."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test").with_goal("Objective").with_tags("tag1", "tag2", "tag3").build()
        )
        assert len(blueprint.tags) == 3
        assert "tag1" in blueprint.tags
        assert "tag2" in blueprint.tags

    def test_with_metadata(self) -> None:
        """Test with_metadata method."""
        blueprint = (
            BlueprintBuilder("bp-1", "Test")
            .with_goal("Objective")
            .with_metadata(key1="value1", key2=42)
            .build()
        )
        assert blueprint.metadata["key1"] == "value1"
        assert blueprint.metadata["key2"] == 42

    def test_chaining(self) -> None:
        """Test all methods can be chained."""
        blueprint = (
            BlueprintBuilder("bp-1", "Full Blueprint")
            .with_description("Complete blueprint")
            .with_goal(
                "Complete the task",
                success_criteria=["Done"],
                constraints=["On time"],
            )
            .with_style(tone="professional", format="html")
            .add_participant("Writer", "Content Writer")
            .add_participant("Reviewer", "Quality Reviewer")
            .with_instruction("Follow the guide")
            .with_version("1.5")
            .with_tags("important", "urgent")
            .with_metadata(priority="high")
            .build()
        )

        assert blueprint.id == "bp-1"
        assert blueprint.description == "Complete blueprint"
        assert len(blueprint.participants) == 2
        assert len(blueprint.tags) == 2


# =============================================================================
# BlueprintSchemaRule Tests
# =============================================================================


class TestBlueprintSchemaRule:
    """Tests for BlueprintSchemaRule."""

    @pytest.mark.asyncio
    async def test_valid_blueprint_instance(self) -> None:
        """Test valid Blueprint instance passes."""
        rule = BlueprintSchemaRule()
        blueprint = create_mock_blueprint()
        result = await rule.check(blueprint)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_valid_dict(self) -> None:
        """Test valid dict passes."""
        rule = BlueprintSchemaRule()
        data = {
            "id": "bp-1",
            "name": "Test",
            "scene_goal": {"objective": "Test objective"},
        }
        result = await rule.check(data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_missing_id(self) -> None:
        """Test missing id fails."""
        rule = BlueprintSchemaRule()
        data = {"name": "Test", "scene_goal": {"objective": "Test"}}
        result = await rule.check(data)
        assert result.passed is False
        assert any(e.code == "MISSING_ID" for e in result.errors)

    @pytest.mark.asyncio
    async def test_missing_name(self) -> None:
        """Test missing name fails."""
        rule = BlueprintSchemaRule()
        data = {"id": "bp-1", "scene_goal": {"objective": "Test"}}
        result = await rule.check(data)
        assert result.passed is False
        assert any(e.code == "MISSING_NAME" for e in result.errors)

    @pytest.mark.asyncio
    async def test_missing_scene_goal(self) -> None:
        """Test missing scene_goal fails."""
        rule = BlueprintSchemaRule()
        data = {"id": "bp-1", "name": "Test"}
        result = await rule.check(data)
        assert result.passed is False
        assert any(e.code == "MISSING_GOAL" for e in result.errors)

    @pytest.mark.asyncio
    async def test_missing_objective_in_scene_goal(self) -> None:
        """Test missing objective in scene_goal fails."""
        rule = BlueprintSchemaRule()
        data = {"id": "bp-1", "name": "Test", "scene_goal": {}}
        result = await rule.check(data)
        assert result.passed is False
        assert any(e.code == "MISSING_OBJECTIVE" for e in result.errors)

    @pytest.mark.asyncio
    async def test_invalid_type(self) -> None:
        """Test invalid type fails."""
        rule = BlueprintSchemaRule()
        result = await rule.check("not a dict")
        assert result.passed is False
        assert result.errors[0].code == "INVALID_TYPE"

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test rule name property."""
        rule = BlueprintSchemaRule(name="custom_schema")
        assert rule.name == "custom_schema"


# =============================================================================
# BlueprintContentRule Tests
# =============================================================================


class TestBlueprintContentRule:
    """Tests for BlueprintContentRule."""

    @pytest.mark.asyncio
    async def test_valid_content(self) -> None:
        """Test valid content passes."""
        rule = BlueprintContentRule()
        blueprint = create_mock_blueprint(objective="This is a sufficiently long objective")
        result = await rule.check(blueprint)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_objective_too_short(self) -> None:
        """Test short objective fails."""
        rule = BlueprintContentRule(min_objective_length=20)
        blueprint = create_mock_blueprint(objective="Short")
        result = await rule.check(blueprint)
        assert result.passed is False
        assert any(e.code == "OBJECTIVE_TOO_SHORT" for e in result.errors)

    @pytest.mark.asyncio
    async def test_instruction_too_long(self) -> None:
        """Test long instruction fails."""
        rule = BlueprintContentRule(max_instruction_length=50)
        blueprint = create_mock_blueprint(
            objective="Valid objective here",
            instruction="x" * 100,
        )
        result = await rule.check(blueprint)
        assert result.passed is False
        assert any(e.code == "INSTRUCTION_TOO_LONG" for e in result.errors)

    @pytest.mark.asyncio
    async def test_duplicate_participant_names(self) -> None:
        """Test duplicate participant names fails."""
        rule = BlueprintContentRule()
        goal = SceneGoal(objective="Valid objective here")
        participants = (
            Participant(name="Agent", role="Helper"),
            Participant(name="Agent", role="Another Role"),  # Duplicate
        )
        blueprint = Blueprint(
            id="bp-1",
            name="Test",
            scene_goal=goal,
            participants=participants,
        )
        result = await rule.check(blueprint)
        assert result.passed is False
        assert any(e.code == "DUPLICATE_PARTICIPANT" for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_role_warning(self) -> None:
        """Test empty participant role generates warning."""
        rule = BlueprintContentRule()
        goal = SceneGoal(objective="Valid objective here")
        participant = Participant(name="Agent", role="")
        blueprint = Blueprint(
            id="bp-1",
            name="Test",
            scene_goal=goal,
            participants=(participant,),
        )
        result = await rule.check(blueprint)
        # Should pass but with warning
        assert any(w.code == "EMPTY_ROLE" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_no_description_warning(self) -> None:
        """Test missing description generates warning."""
        rule = BlueprintContentRule()
        blueprint = create_mock_blueprint(objective="Valid objective here")
        result = await rule.check(blueprint)
        assert any(w.code == "NO_DESCRIPTION" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_dict_input(self) -> None:
        """Test validation with dict input."""
        rule = BlueprintContentRule()
        data = {
            "id": "bp-1",
            "name": "Test",
            "scene_goal": {"objective": "Valid objective here"},
        }
        result = await rule.check(data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_invalid_type(self) -> None:
        """Test invalid type fails."""
        rule = BlueprintContentRule()
        result = await rule.check("not a blueprint")
        assert result.passed is False
        assert result.errors[0].code == "INVALID_TYPE"

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test rule name property."""
        rule = BlueprintContentRule(name="custom_content")
        assert rule.name == "custom_content"


# =============================================================================
# Mock Utilities Tests
# =============================================================================


class TestCreateMockBlueprint:
    """Tests for create_mock_blueprint function."""

    def test_default_values(self) -> None:
        """Test default values are used."""
        blueprint = create_mock_blueprint()
        assert blueprint.id == "mock-bp-1"
        assert blueprint.name == "Mock Blueprint"
        assert blueprint.scene_goal.objective == "Test objective for mocking"

    def test_custom_id(self) -> None:
        """Test custom id."""
        blueprint = create_mock_blueprint(id="custom-id")
        assert blueprint.id == "custom-id"

    def test_custom_name(self) -> None:
        """Test custom name."""
        blueprint = create_mock_blueprint(name="Custom Name")
        assert blueprint.name == "Custom Name"

    def test_custom_objective(self) -> None:
        """Test custom objective."""
        blueprint = create_mock_blueprint(objective="Custom objective")
        assert blueprint.scene_goal.objective == "Custom objective"

    def test_kwargs_passthrough(self) -> None:
        """Test additional kwargs are passed to Blueprint."""
        blueprint = create_mock_blueprint(
            description="Test description",
            version="2.0",
            tags=("tag1", "tag2"),
        )
        assert blueprint.description == "Test description"
        assert blueprint.version == "2.0"
        assert blueprint.tags == ("tag1", "tag2")


class TestMockBlueprintRegistry:
    """Tests for MockBlueprintRegistry."""

    def test_register_and_get(self) -> None:
        """Test registering and retrieving a blueprint."""
        registry = MockBlueprintRegistry()
        blueprint = create_mock_blueprint(id="bp-1")
        registry.register(blueprint)

        retrieved = registry.get("bp-1")
        assert retrieved is not None
        assert retrieved.id == "bp-1"

    def test_get_nonexistent(self) -> None:
        """Test getting a nonexistent blueprint returns None."""
        registry = MockBlueprintRegistry()
        result = registry.get("nonexistent")
        assert result is None

    def test_list_all_empty(self) -> None:
        """Test list_all on empty registry."""
        registry = MockBlueprintRegistry()
        result = registry.list_all()
        assert result == []

    def test_list_all_with_blueprints(self) -> None:
        """Test list_all with blueprints."""
        registry = MockBlueprintRegistry()
        registry.register(create_mock_blueprint(id="bp-1"))
        registry.register(create_mock_blueprint(id="bp-2"))
        registry.register(create_mock_blueprint(id="bp-3"))

        result = registry.list_all()
        assert len(result) == 3

    def test_overwrite_existing(self) -> None:
        """Test registering with same id overwrites."""
        registry = MockBlueprintRegistry()
        registry.register(create_mock_blueprint(id="bp-1", name="First"))
        registry.register(create_mock_blueprint(id="bp-1", name="Second"))

        retrieved = registry.get("bp-1")
        assert retrieved is not None
        assert retrieved.name == "Second"
        assert len(registry.list_all()) == 1

    def test_clear(self) -> None:
        """Test clearing the registry."""
        registry = MockBlueprintRegistry()
        registry.register(create_mock_blueprint(id="bp-1"))
        registry.register(create_mock_blueprint(id="bp-2"))
        assert len(registry.list_all()) == 2

        registry.clear()
        assert len(registry.list_all()) == 0
        assert registry.get("bp-1") is None
