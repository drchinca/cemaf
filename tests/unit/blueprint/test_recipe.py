"""Unit tests for `cemaf.blueprint.recipe.parse_recipe`."""

from __future__ import annotations

import pytest

from cemaf.blueprint.recipe import RecipeValidationError, parse_recipe


class TestRequiredFields:
    def test_missing_id_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="'id' is required"):
            parse_recipe(recipe={"name": "X", "goal": "obj"})

    def test_missing_name_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="'name' is required"):
            parse_recipe(recipe={"id": "x", "goal": "obj"})

    def test_missing_goal_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="goal"):
            parse_recipe(recipe={"id": "x", "name": "X"})

    def test_defaults_fill_missing_id_and_name(self) -> None:
        bp = parse_recipe(
            recipe={"goal": "obj"},
            default_id="fallback-id",
            default_name="Fallback Name",
        )
        assert bp.id == "fallback-id"
        assert bp.name == "Fallback Name"

    def test_recipe_id_wins_over_default(self) -> None:
        bp = parse_recipe(
            recipe={"id": "from-recipe", "name": "N", "goal": "o"},
            default_id="from-default",
        )
        assert bp.id == "from-recipe"

    def test_recipe_name_wins_over_default(self) -> None:
        bp = parse_recipe(
            recipe={"id": "i", "name": "from-recipe", "goal": "o"},
            default_name="from-default",
        )
        assert bp.name == "from-recipe"


class TestGoalParsing:
    def test_string_goal(self) -> None:
        bp = parse_recipe(recipe={"id": "i", "name": "n", "goal": "do x"})
        assert bp.scene_goal.objective == "do x"
        assert bp.scene_goal.priority == 1

    def test_dict_goal_with_all_fields(self) -> None:
        bp = parse_recipe(
            recipe={
                "id": "i",
                "name": "n",
                "goal": {
                    "objective": "ship it",
                    "success_criteria": ["a", "b"],
                    "constraints": ["c"],
                    "priority": 5,
                },
            }
        )
        assert bp.scene_goal.objective == "ship it"
        assert bp.scene_goal.success_criteria == ("a", "b")
        assert bp.scene_goal.constraints == ("c",)
        assert bp.scene_goal.priority == 5

    def test_goal_wrong_type_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="string or dict"):
            parse_recipe(recipe={"id": "i", "name": "n", "goal": 42})

    def test_goal_objective_must_be_nonempty_string(self) -> None:
        with pytest.raises(RecipeValidationError, match="objective"):
            parse_recipe(recipe={"id": "i", "name": "n", "goal": {"objective": ""}})
        with pytest.raises(RecipeValidationError, match="objective"):
            parse_recipe(recipe={"id": "i", "name": "n", "goal": {}})

    def test_goal_priority_must_be_int(self) -> None:
        with pytest.raises(RecipeValidationError, match="priority"):
            parse_recipe(
                recipe={
                    "id": "i",
                    "name": "n",
                    "goal": {"objective": "o", "priority": "high"},
                }
            )


class TestStyleParsing:
    def test_style_omitted_yields_empty_style(self) -> None:
        bp = parse_recipe(recipe={"id": "i", "name": "n", "goal": "o"})
        assert bp.style_guide.is_empty()

    def test_style_with_all_fields(self) -> None:
        bp = parse_recipe(
            recipe={
                "id": "i",
                "name": "n",
                "goal": "o",
                "style": {
                    "tone": "formal",
                    "format": "markdown",
                    "length_hint": "brief",
                    "vocabulary": ["v1"],
                    "avoid": ["a1"],
                    "examples": ["e1"],
                },
            }
        )
        assert bp.style_guide.tone == "formal"
        assert bp.style_guide.vocabulary == ("v1",)
        assert bp.style_guide.avoid == ("a1",)
        assert bp.style_guide.examples == ("e1",)

    def test_style_wrong_type_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="'style' must be a dict"):
            parse_recipe(recipe={"id": "i", "name": "n", "goal": "o", "style": "formal"})


class TestAsTupleValidation:
    def test_bare_string_tags_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="expects a list of strings"):
            parse_recipe(
                recipe={"id": "i", "name": "n", "goal": "o", "tags": "notalist"},
            )

    def test_non_list_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="must be a list"):
            parse_recipe(recipe={"id": "i", "name": "n", "goal": "o", "tags": 42})

    def test_non_string_item_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match=r"tags'\[1\]"):
            parse_recipe(
                recipe={"id": "i", "name": "n", "goal": "o", "tags": ["ok", 42]},
            )

    def test_none_coerces_to_empty_tuple(self) -> None:
        # Achievable via missing key, which yields None from .get().
        bp = parse_recipe(recipe={"id": "i", "name": "n", "goal": "o"})
        assert bp.tags == ()


class TestLongFormKeys:
    def test_scene_goal_long_form_accepted(self) -> None:
        bp = parse_recipe(recipe={"id": "i", "name": "n", "scene_goal": {"objective": "obj"}})
        assert bp.scene_goal.objective == "obj"

    def test_style_guide_long_form_accepted(self) -> None:
        bp = parse_recipe(
            recipe={
                "id": "i",
                "name": "n",
                "goal": "o",
                "style_guide": {"tone": "curt"},
            }
        )
        assert bp.style_guide.tone == "curt"

    def test_short_form_beats_long_form(self) -> None:
        bp = parse_recipe(
            recipe={
                "id": "i",
                "name": "n",
                "goal": "short wins",
                "scene_goal": {"objective": "long should lose"},
            }
        )
        assert bp.scene_goal.objective == "short wins"


class TestEntitiesParsing:
    def test_entities_omitted_yields_empty(self) -> None:
        bp = parse_recipe(recipe={"id": "i", "name": "n", "goal": "o"})
        assert bp.entities == ()

    def test_entities_non_list_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="must be a list"):
            parse_recipe(
                recipe={"id": "i", "name": "n", "goal": "o", "entities": {"wrong": "shape"}},
            )

    def test_entity_item_non_dict_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match=r"entities\[0\]"):
            parse_recipe(
                recipe={"id": "i", "name": "n", "goal": "o", "entities": ["notadict"]},
            )


class TestWholeRecipeShape:
    def test_recipe_not_a_dict_raises(self) -> None:
        with pytest.raises(RecipeValidationError, match="Recipe must be a dict"):
            parse_recipe(recipe="not a dict")  # type: ignore[arg-type]

    def test_empty_recipe_needs_defaults(self) -> None:
        # With no defaults, empty recipe fails on id.
        with pytest.raises(RecipeValidationError, match="'id' is required"):
            parse_recipe(recipe={})

    def test_full_happy_path(self) -> None:
        bp = parse_recipe(
            recipe={
                "id": "rich",
                "name": "Rich",
                "description": "desc",
                "version": "2.1",
                "tags": ["a", "b"],
                "instruction": "do the thing",
                "goal": {"objective": "o", "priority": 3},
                "style": {"tone": "neutral"},
            }
        )
        assert bp.id == "rich"
        assert bp.description == "desc"
        assert bp.version == "2.1"
        assert bp.tags == ("a", "b")
        assert bp.instruction == "do the thing"
        assert bp.scene_goal.priority == 3
        assert bp.style_guide.tone == "neutral"
