"""
Blueprint module for defining scene blueprints.

Blueprints describe the structure and requirements for content generation scenes.
"""

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.mock import MockBlueprintRegistry, create_mock_blueprint
from cemaf.blueprint.rules import BlueprintContentRule, BlueprintSchemaRule
from cemaf.blueprint.schema import (
    Blueprint,
    Participant,
    SceneGoal,
    StyleGuide,
)

__all__ = [
    # Schema models
    "Blueprint",
    "Participant",
    "SceneGoal",
    "StyleGuide",
    # Builder
    "BlueprintBuilder",
    # Validation rules
    "BlueprintContentRule",
    "BlueprintSchemaRule",
    # Mocks for testing
    "MockBlueprintRegistry",
    "create_mock_blueprint",
]
