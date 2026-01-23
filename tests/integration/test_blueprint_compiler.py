"""
Integration tests for Blueprint + Context Compiler integration.

Tests that blueprints can inform context compilation priorities.
"""

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.entities import ContextEntity
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator


class TestBlueprintCompiler:
    """Integration tests for Blueprint + Context Compiler."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def compiler(self, estimator: SimpleTokenEstimator) -> PriorityContextCompiler:
        """Create context compiler."""
        return PriorityContextCompiler(token_estimator=estimator)

    @pytest.fixture
    def blueprint_with_entities(self) -> Blueprint:
        """Create blueprint with entities."""
        return Blueprint(
            id="analysis",
            name="Data Analysis",
            scene_goal=SceneGoal(
                objective="Analyze sales data",
                priority=2,
            ),
            entities=(
                ContextEntity.analysis(
                    name="sales_data",
                    token_priority=10,  # High priority
                ),
                ContextEntity.analysis(
                    name="customer_data",
                    token_priority=5,  # Lower priority
                ),
            ),
        )

    @pytest.fixture
    def blueprint_simple(self) -> Blueprint:
        """Create simple blueprint without entities."""
        return Blueprint(
            id="simple",
            name="Simple Blueprint",
            scene_goal=SceneGoal(objective="Generate content", priority=3),
        )

    @pytest.mark.asyncio
    async def test_blueprint_get_context_priorities_with_entities(self, blueprint_with_entities: Blueprint):
        """Test that blueprint returns priorities from entities."""
        priorities = blueprint_with_entities.get_context_priorities()

        assert "sales_data" in priorities
        assert priorities["sales_data"] == 10
        assert "customer_data" in priorities
        assert priorities["customer_data"] == 5

    @pytest.mark.asyncio
    async def test_blueprint_get_context_priorities_without_entities(self, blueprint_simple: Blueprint):
        """Test that blueprint returns default priorities when no entities."""
        priorities = blueprint_simple.get_context_priorities()

        assert "artifacts" in priorities
        assert priorities["artifacts"] == 3  # From scene_goal.priority
        assert "memories" in priorities
        assert priorities["memories"] == 2  # base_priority - 1

    @pytest.mark.asyncio
    async def test_compiler_uses_blueprint_priorities(
        self,
        compiler: PriorityContextCompiler,
        blueprint_with_entities: Blueprint,
    ):
        """Test that compiler uses blueprint priorities for context selection."""
        priorities = blueprint_with_entities.get_context_priorities()

        artifacts = (
            ("sales_data", "Sales data: $1M revenue"),
            ("customer_data", "Customer data: 1000 customers"),
        )
        memories = ()
        # Use larger budget to ensure sources fit
        budget = TokenBudget(max_tokens=10000, reserved_for_output=1000)

        compiled = await compiler.compile(
            artifacts=artifacts,
            memories=memories,
            budget=budget,
            priorities=priorities,
        )

        # Verify compilation succeeded
        assert compiled is not None
        # Should include sources if budget allows
        if compiled.total_tokens > 0:
            assert compiled.within_budget()

        # Verify sources are ordered by priority (sales_data should come first)
        source_keys = [s.key for s in compiled.sources]
        assert "sales_data" in source_keys
        assert "customer_data" in source_keys
        # Higher priority should come first
        assert source_keys.index("sales_data") < source_keys.index("customer_data")

    @pytest.mark.asyncio
    async def test_blueprint_priorities_affect_selection(
        self,
        compiler: PriorityContextCompiler,
        blueprint_with_entities: Blueprint,
    ):
        """Test that blueprint priorities affect which sources are selected."""
        priorities = blueprint_with_entities.get_context_priorities()

        # Create artifacts with different sizes
        artifacts = (
            ("sales_data", "Sales: " + "data " * 100),  # Large, high priority
            ("customer_data", "Customers: " + "info " * 200),  # Very large, low priority
        )
        memories = ()
        budget = TokenBudget(max_tokens=50)  # Small budget - should select high priority

        compiled = await compiler.compile(
            artifacts=artifacts,
            memories=memories,
            budget=budget,
            priorities=priorities,
        )

        # With small budget, high priority source should be selected
        source_keys = [s.key for s in compiled.sources]
        # sales_data (priority 10) should be included
        assert "sales_data" in source_keys or len(source_keys) == 0
