"""Declarative recipe parser — dict spec → Blueprint.

A recipe is a plain JSON/YAML-compatible dict that CEMAF parses into a
full `Blueprint`. This is the third storage kind in `BlueprintLibrary`,
alongside SNAPSHOT (inline serialized Blueprint) and FACTORY (Python
import path). Recipes let non-Python contributors author blueprints by
writing data, not code.

Minimal recipe:

    {
        "name": "My Blueprint",
        "goal": "Do the thing"
    }

Full recipe (all known fields):

    {
        "name": "Product Announcement",
        "description": "Blueprint for external launch posts",
        "version": "1.2",
        "tags": ["content", "marketing"],
        "goal": {
            "objective": "Write a product announcement",
            "success_criteria": ["Clear value prop", "Concrete CTA"],
            "constraints": ["Under 300 words"],
            "priority": 2
        },
        "style": {
            "tone": "confident",
            "format": "markdown"
        },
        "instruction": "Lead with the user benefit.",
        "entities": [
            {"name": "release_notes", "entity_type": "content"}
        ]
    }

Keys are intentionally short (`goal`, not `scene_goal`; `style`, not
`style_guide`) — recipes optimize for human authoring, not one-to-one
mapping with the `Blueprint` class. The parser handles both the short
and long forms, so an existing `Blueprint.to_dict()` output also parses.
"""

from __future__ import annotations

from typing import Any

from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.entities import ContextEntity


class RecipeValidationError(ValueError):
    """Raised when a recipe dict is missing required fields or malformed."""


def _as_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise RecipeValidationError(f"Field {field_name!r} expects a list of strings, got a bare string.")
    if not isinstance(value, list | tuple):
        raise RecipeValidationError(f"Field {field_name!r} must be a list; got {type(value).__name__}.")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise RecipeValidationError(
                f"Field {field_name!r}[{i}] must be a string; got {type(item).__name__}."
            )
        out.append(item)
    return tuple(out)


def _parse_goal(raw: Any) -> SceneGoal:
    if raw is None:
        raise RecipeValidationError(
            "Recipe must declare a 'goal' (or 'scene_goal') — a string objective or a dict."
        )
    if isinstance(raw, str):
        return SceneGoal(objective=raw)
    if not isinstance(raw, dict):
        raise RecipeValidationError(f"Recipe 'goal' must be a string or dict; got {type(raw).__name__}.")
    objective = raw.get("objective")
    if not isinstance(objective, str) or not objective:
        raise RecipeValidationError("Recipe 'goal.objective' is required and must be a non-empty string.")
    priority = raw.get("priority", 1)
    if not isinstance(priority, int):
        raise RecipeValidationError(f"Recipe 'goal.priority' must be an int; got {type(priority).__name__}.")
    return SceneGoal(
        objective=objective,
        success_criteria=_as_tuple(raw.get("success_criteria"), field_name="goal.success_criteria"),
        constraints=_as_tuple(raw.get("constraints"), field_name="goal.constraints"),
        priority=priority,
    )


def _parse_style(raw: Any) -> StyleGuide:
    if raw is None:
        return StyleGuide()
    if not isinstance(raw, dict):
        raise RecipeValidationError(f"Recipe 'style' must be a dict; got {type(raw).__name__}.")
    return StyleGuide(
        tone=raw.get("tone", ""),
        format=raw.get("format", ""),
        length_hint=raw.get("length_hint", ""),
        vocabulary=_as_tuple(raw.get("vocabulary"), field_name="style.vocabulary"),
        avoid=_as_tuple(raw.get("avoid"), field_name="style.avoid"),
        examples=_as_tuple(raw.get("examples"), field_name="style.examples"),
    )


def _parse_entities(raw: Any) -> tuple[ContextEntity, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        raise RecipeValidationError(f"Recipe 'entities' must be a list; got {type(raw).__name__}.")
    out: list[ContextEntity] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RecipeValidationError(f"Recipe 'entities[{i}]' must be a dict; got {type(item).__name__}.")
        try:
            out.append(ContextEntity.model_validate(item))
        except Exception as exc:
            raise RecipeValidationError(f"Recipe 'entities[{i}]' failed validation: {exc}") from exc
    return tuple(out)


def parse_recipe(
    *,
    recipe: dict[str, Any],
    default_id: str | None = None,
    default_name: str | None = None,
) -> Blueprint:
    """Parse a declarative recipe dict into a `Blueprint`.

    `default_id` and `default_name` are used only when the recipe omits
    them — the library provides its own entry id/title as fallback. If
    the recipe carries explicit id/name, the recipe wins.
    """
    if not isinstance(recipe, dict):
        raise RecipeValidationError(f"Recipe must be a dict; got {type(recipe).__name__}.")

    bp_id = recipe.get("id", default_id)
    if not isinstance(bp_id, str) or not bp_id:
        raise RecipeValidationError("Recipe 'id' is required (or pass default_id).")

    name = recipe.get("name", default_name)
    if not isinstance(name, str) or not name:
        raise RecipeValidationError("Recipe 'name' is required (or pass default_name).")

    goal_raw = recipe.get("goal", recipe.get("scene_goal"))
    style_raw = recipe.get("style", recipe.get("style_guide"))

    return Blueprint(
        id=bp_id,
        name=name,
        description=recipe.get("description", ""),
        instruction=recipe.get("instruction", ""),
        version=recipe.get("version", "1.0"),
        tags=_as_tuple(recipe.get("tags"), field_name="tags"),
        scene_goal=_parse_goal(goal_raw),
        style_guide=_parse_style(style_raw),
        entities=_parse_entities(recipe.get("entities")),
    )


__all__ = ["RecipeValidationError", "parse_recipe"]
