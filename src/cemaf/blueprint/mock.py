"""Mock implementations for blueprint testing."""

from cemaf.blueprint.schema import Blueprint, SceneGoal


def create_mock_blueprint(
    id: str = "mock-bp-1",
    name: str = "Mock Blueprint",
    objective: str = "Test objective for mocking",
    **kwargs,
) -> Blueprint:
    """Create a mock blueprint for testing."""
    scene_goal = SceneGoal(objective=objective)
    return Blueprint(
        id=id,
        name=name,
        scene_goal=scene_goal,
        **kwargs,
    )


class MockBlueprintRegistry:
    """Mock registry for storing and retrieving blueprints."""

    def __init__(self) -> None:
        self._blueprints: dict[str, Blueprint] = {}

    def register(self, blueprint: Blueprint) -> None:
        self._blueprints[blueprint.id] = blueprint

    def get(self, id: str) -> Blueprint | None:
        return self._blueprints.get(id)

    def list_all(self) -> list[Blueprint]:
        return list(self._blueprints.values())

    def clear(self) -> None:
        self._blueprints.clear()
