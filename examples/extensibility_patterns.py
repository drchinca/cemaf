"""
Demonstrate Blueprint Extensibility: Beyond Predefined Literals.

CEMAF Blueprint uses STRONG TYPING for deterministic LLM inputs - this is critical!

The Literal types define common patterns and ensure type safety. For domain-specific
extensions, use `# type: ignore` to signal intentional extension beyond the types.

This gives you BOTH:
1. Deterministic behavior for standard cases (strong types)
2. Flexibility for domain-specific needs (runtime extensibility with type: ignore)

The strong typing is a HIGHLY IMPORTANT piece of the puzzle - it ensures
deterministic LLM inputs while allowing controlled extensibility.

Run: uv run python examples/extensibility_patterns.py
"""

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.entities import ContextEntity


def example_1_scientific_research() -> None:
    """Example 1: Scientific Research - Custom methodology and depth values."""
    print("\n" + "=" * 80)
    print("EXAMPLE 1: Scientific Research Blueprint")
    print("Using custom values: 'peer-reviewed-academic', 'randomized-controlled-trial'")
    print("=" * 80)

    blueprint = (
        BlueprintBuilder("research-001", "Clinical Trial Analysis")
        .with_goal(
            "Analyze Phase III clinical trial results for efficacy and safety",
            success_criteria=[
                "Statistical significance (p < 0.05)",
                "Intent-to-treat analysis completed",
                "Adverse events categorized by severity",
            ],
        )
        .add_entity(
            ContextEntity.content(
                name="manuscript_author",
                description="Write peer-reviewed manuscript",
                style="peer-reviewed-academic",  # type: ignore[arg-type]  # Custom value!
                perspective="third-person",
                tone="objective-clinical",
                token_priority=8,
            )
        )
        .add_entity(
            ContextEntity.analysis(
                name="statistician",
                description="Perform statistical analysis of trial data",
                methodology="randomized-controlled-trial",  # type: ignore[arg-type]  # Custom value!
                depth="meta-analysis",  # type: ignore[arg-type]  # Custom value!
                focus_areas=("primary-endpoint", "secondary-outcomes", "subgroup-analysis"),
                token_priority=10,
            )
        )
        .add_entity(
            ContextEntity.validation(
                name="regulatory_reviewer",
                description="Validate regulatory compliance",
                validation_type="fda-510k-compliance",  # type: ignore[arg-type]  # Custom value!
                rules=("good-clinical-practice", "informed-consent", "data-integrity"),
                token_priority=10,
            )
        )
        .with_instruction(
            "Analyze clinical trial data following FDA guidelines. "
            "Include statistical methods, results tables, safety analysis, and conclusions."
        )
        .build()
    )

    print(blueprint.to_prompt())
    print("\nNOTE: Custom values like 'peer-reviewed-academic', 'randomized-controlled-trial',")
    print("      'meta-analysis', and 'fda-510k-compliance' work perfectly at runtime!")


def example_2_financial_analysis() -> None:
    """Example 2: Financial Analysis - Custom validation and methodology."""
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Financial Analysis Blueprint")
    print("Using custom values: 'sox-compliance', 'monte-carlo-simulation'")
    print("=" * 80)

    blueprint = (
        BlueprintBuilder("fin-risk-001", "Portfolio Risk Assessment")
        .with_goal(
            "Assess portfolio risk using quantitative models",
            success_criteria=[
                "VaR calculated at 95% confidence",
                "Stress test scenarios executed",
                "Correlation matrix validated",
            ],
        )
        .add_entity(
            ContextEntity.analysis(
                name="risk_modeler",
                description="Build risk models for portfolio analysis",
                methodology="monte-carlo-simulation",  # type: ignore[arg-type]  # Custom value!
                depth="stochastic-modeling",  # type: ignore[arg-type]  # Custom value!
                focus_areas=("value-at-risk", "expected-shortfall", "correlation-breakdown"),
                token_priority=9,
            )
        )
        .add_entity(
            ContextEntity.validation(
                name="compliance_officer",
                description="Ensure SOX and regulatory compliance",
                validation_type="sox-compliance",  # type: ignore[arg-type]  # Custom value!
                rules=("internal-controls", "audit-trail", "segregation-of-duties"),
                token_priority=10,
            )
        )
        .add_entity(
            ContextEntity.technical(
                name="risk_system",
                description="Risk calculation engine",
                domain="quantitative-finance",  # Custom value!
                audience_level="quant-trader",  # type: ignore[arg-type]  # Custom value!
                token_priority=8,
            )
        )
        .with_instruction(
            "Perform portfolio risk analysis using Monte Carlo simulations. "
            "Calculate VaR, CVaR, and stress test results with full audit trail."
        )
        .build()
    )

    print(blueprint.to_prompt())
    print("\nNOTE: Financial domain values like 'sox-compliance', 'monte-carlo-simulation',")
    print("      and 'quantitative-finance' extend Blueprint to specialized use cases!")


def example_3_creative_writing() -> None:
    """Example 3: Creative Writing - Custom style and perspective values."""
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Creative Writing Blueprint")
    print("Using custom values: 'magical-realism', 'unreliable-narrator'")
    print("=" * 80)

    blueprint = (
        BlueprintBuilder("story-001", "Dystopian Short Story")
        .with_goal(
            "Write a dystopian short story with magical realism elements",
            success_criteria=[
                "World-building establishes near-future setting",
                "Protagonist has clear character arc",
                "Magical elements integrated naturally",
            ],
        )
        .add_entity(
            ContextEntity.content(
                name="narrator",
                description="Tell story from protagonist perspective",
                style="magical-realism",  # type: ignore[arg-type]  # Custom value!
                perspective="unreliable-narrator",  # type: ignore[arg-type]  # Custom value!
                tone="dystopian-hopeful",  # Custom value!
                traits=("memory-fragmented", "time-non-linear", "perception-altered"),
                token_priority=10,
            )
        )
        .add_entity(
            ContextEntity.content(
                name="world_builder",
                description="Establish setting and atmosphere",
                style="neo-noir-cyberpunk",  # type: ignore[arg-type]  # Custom value!
                tone="atmospheric-oppressive",
                token_priority=8,
            )
        )
        .with_instruction(
            "Write a 3000-word short story about a memory-trader in a surveillance state. "
            "Use unreliable narration and blend magical realism with dystopian elements."
        )
        .build()
    )

    print(blueprint.to_prompt())
    print("\nNOTE: Creative writing benefits from highly specific styles like 'magical-realism'")
    print("      and 'neo-noir-cyberpunk' that don't exist in default Literals!")


def example_4_data_engineering() -> None:
    """Example 4: Data Engineering - Custom domain and validation values."""
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Data Engineering Blueprint")
    print("Using custom values: 'streaming-architecture', 'data-quality-sla'")
    print("=" * 80)

    blueprint = (
        BlueprintBuilder("stream-pipeline-001", "Real-Time Event Processing")
        .with_goal(
            "Design real-time event processing pipeline for IoT sensors",
            success_criteria=[
                "Sub-second latency (p99)",
                "Exactly-once semantics guaranteed",
                "Auto-scaling based on throughput",
            ],
        )
        .add_entity(
            ContextEntity.technical(
                name="kafka_cluster",
                description="Event streaming backbone",
                domain="streaming-architecture",  # Custom value!
                audience_level="platform-engineer",  # type: ignore[arg-type]  # Custom value!
                token_priority=9,
            )
        )
        .add_entity(
            ContextEntity.analysis(
                name="stream_processor",
                description="Process and enrich event streams",
                methodology="stateful-stream-processing",  # type: ignore[arg-type]  # Custom value!
                depth="windowed-aggregation",  # type: ignore[arg-type]  # Custom value!
                focus_areas=("event-time-semantics", "late-data-handling", "watermarks"),
                token_priority=8,
            )
        )
        .add_entity(
            ContextEntity.validation(
                name="sla_monitor",
                description="Validate data quality and SLA compliance",
                validation_type="data-quality-sla",  # type: ignore[arg-type]  # Custom value!
                rules=(
                    "latency-p99-under-1s",
                    "completeness-99.9",
                    "exactly-once-delivery",
                ),
                token_priority=10,
            )
        )
        .with_instruction(
            "Design streaming pipeline using Kafka, Flink, and ClickHouse. "
            "Include windowing strategy, state management, and monitoring dashboards."
        )
        .build()
    )

    print(blueprint.to_prompt())
    print("\nNOTE: Data engineering domain values like 'streaming-architecture' and")
    print("      'data-quality-sla' show how Blueprint adapts to technical domains!")


def main() -> None:
    """Run all extensibility examples."""
    print("\n" + "=" * 80)
    print("CEMAF BLUEPRINT EXTENSIBILITY PATTERNS")
    print("=" * 80)
    print("\nBlueprint is a PROTOCOL - the Literal types guide you with common patterns,")
    print("but you can use ANY string value. Python doesn't enforce Literals at runtime.")
    print("\nThis demonstrates CEMAF's philosophy: flexible primitives over prescriptive frameworks.")

    # Run all examples
    example_1_scientific_research()
    example_2_financial_analysis()
    example_3_creative_writing()
    example_4_data_engineering()

    print("\n" + "=" * 80)
    print("SUMMARY: Strong Typing + Controlled Extensibility")
    print("=" * 80)
    print("✅ Strong Literal types ensure DETERMINISTIC LLM INPUTS (critical!)")
    print("✅ Type safety catches errors and guides developers with IDE autocomplete")
    print("✅ Runtime allows custom values via `# type: ignore` for domain extensions")
    print("✅ Use **extra metadata for additional domain-specific fields")
    print("✅ This dual approach gives both reliability and flexibility")
    print("\nWHY THIS MATTERS:")
    print("  • Deterministic prompts = predictable LLM behavior")
    print("  • Strong types = fewer bugs, better tooling")
    print("  • Controlled extensibility = domain-specific customization")
    print("\nCEMAF: Context Engineering with Maximum Adaptability and Flexibility")


if __name__ == "__main__":
    main()
