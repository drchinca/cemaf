"""
Comprehensive tests for Blueprint with all entity types and permutations.

Tests systematic combinations of all 6 entity types (CONTENT, ANALYSIS, TECHNICAL,
COMPARATIVE, EDUCATIONAL, VALIDATION) across different use cases to ensure
Blueprint works generically for any task domain.
"""

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.entities import ContextEntity, EntityType


class TestAllEntityTypes:
    """Test each entity type individually in a blueprint."""

    def test_content_entity_only(self) -> None:
        """Test blueprint with only CONTENT entity."""
        blueprint = (
            BlueprintBuilder("content-only", "Content Generation Blueprint")
            .with_goal("Generate engaging blog post about AI")
            .add_entity(
                ContextEntity.content(
                    name="blog_writer",
                    description="Technical blog writer",
                    style="technical",
                    perspective="third-person",
                    tone="professional",
                )
            )
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.CONTENT
        prompt = blueprint.to_prompt()
        assert "Type: Content" in prompt
        assert "blog_writer" in prompt

    def test_analysis_entity_only(self) -> None:
        """Test blueprint with only ANALYSIS entity."""
        blueprint = (
            BlueprintBuilder("analysis-only", "Data Analysis Blueprint")
            .with_goal("Analyze sales trends")
            .add_entity(
                ContextEntity.analysis(
                    name="data_analyst",
                    description="Sales data analyst",
                    methodology="quantitative",
                    depth="comprehensive",
                )
            )
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.ANALYSIS
        prompt = blueprint.to_prompt()
        assert "Type: Analysis" in prompt

    def test_technical_entity_only(self) -> None:
        """Test blueprint with only TECHNICAL entity."""
        blueprint = (
            BlueprintBuilder("technical-only", "Technical Documentation Blueprint")
            .with_goal("Generate API documentation")
            .add_entity(
                ContextEntity.technical(
                    name="api_docs_writer",
                    description="API documentation specialist",
                    domain="software",
                    audience_level="intermediate",
                )
            )
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.TECHNICAL
        prompt = blueprint.to_prompt()
        assert "Type: Technical" in prompt

    def test_comparative_entity_only(self) -> None:
        """Test blueprint with only COMPARATIVE entity."""
        blueprint = (
            BlueprintBuilder("comparative-only", "Comparison Blueprint")
            .with_goal("Compare two database systems")
            .add_entity(
                ContextEntity.comparative(
                    name="system_comparator",
                    description="Database system comparison expert",
                    dimensions=("performance", "cost", "scalability"),
                    format="side-by-side",
                )
            )
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.COMPARATIVE
        prompt = blueprint.to_prompt()
        assert "Type: Comparative" in prompt

    def test_educational_entity_only(self) -> None:
        """Test blueprint with only EDUCATIONAL entity."""
        blueprint = (
            BlueprintBuilder("educational-only", "Teaching Blueprint")
            .with_goal("Explain machine learning concepts")
            .add_entity(
                ContextEntity.educational(
                    name="ml_teacher",
                    description="ML educator",
                    teaching_style="socratic",
                    knowledge_level="beginner",
                )
            )
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.EDUCATIONAL
        prompt = blueprint.to_prompt()
        assert "Type: Educational" in prompt

    def test_validation_entity_only(self) -> None:
        """Test blueprint with only VALIDATION entity."""
        blueprint = (
            BlueprintBuilder("validation-only", "Validation Blueprint")
            .with_goal("Validate data quality")
            .add_entity(
                ContextEntity.validation(
                    name="quality_validator",
                    description="Data quality checker",
                    validation_type="schema",
                    rules=("required_fields", "format_check"),
                )
            )
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.VALIDATION
        prompt = blueprint.to_prompt()
        assert "Type: Validation" in prompt


class TestEntityTypePairs:
    """Test all possible pairs of entity types."""

    def test_content_and_analysis(self) -> None:
        """Test CONTENT + ANALYSIS combination."""
        blueprint = (
            BlueprintBuilder("content-analysis", "Content Analysis Blueprint")
            .with_goal("Analyze and write about market trends")
            .add_entity(ContextEntity.content(name="writer", description="Content writer"))
            .add_entity(ContextEntity.analysis(name="analyst", description="Market analyst"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.CONTENT in types
        assert EntityType.ANALYSIS in types
        assert len(types) == 2

    def test_content_and_technical(self) -> None:
        """Test CONTENT + TECHNICAL combination."""
        blueprint = (
            BlueprintBuilder("content-technical", "Technical Content Blueprint")
            .with_goal("Write technical documentation")
            .add_entity(ContextEntity.content(name="writer", description="Technical writer"))
            .add_entity(ContextEntity.technical(name="engineer", description="Software engineer"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.CONTENT in types
        assert EntityType.TECHNICAL in types

    def test_content_and_comparative(self) -> None:
        """Test CONTENT + COMPARATIVE combination."""
        blueprint = (
            BlueprintBuilder("content-comparative", "Comparative Content Blueprint")
            .with_goal("Write comparison article")
            .add_entity(ContextEntity.content(name="writer", description="Article writer"))
            .add_entity(ContextEntity.comparative(name="comparator", description="Product comparator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.CONTENT in types
        assert EntityType.COMPARATIVE in types

    def test_content_and_educational(self) -> None:
        """Test CONTENT + EDUCATIONAL combination."""
        blueprint = (
            BlueprintBuilder("content-educational", "Educational Content Blueprint")
            .with_goal("Create educational content")
            .add_entity(ContextEntity.content(name="writer", description="Content creator"))
            .add_entity(ContextEntity.educational(name="teacher", description="Educator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.CONTENT in types
        assert EntityType.EDUCATIONAL in types

    def test_content_and_validation(self) -> None:
        """Test CONTENT + VALIDATION combination."""
        blueprint = (
            BlueprintBuilder("content-validation", "Validated Content Blueprint")
            .with_goal("Create validated content")
            .add_entity(ContextEntity.content(name="writer", description="Content writer"))
            .add_entity(ContextEntity.validation(name="reviewer", description="Content reviewer"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.CONTENT in types
        assert EntityType.VALIDATION in types

    def test_analysis_and_technical(self) -> None:
        """Test ANALYSIS + TECHNICAL combination."""
        blueprint = (
            BlueprintBuilder("analysis-technical", "Technical Analysis Blueprint")
            .with_goal("Analyze technical system")
            .add_entity(ContextEntity.analysis(name="analyst", description="System analyst"))
            .add_entity(ContextEntity.technical(name="system", description="Technical system"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.ANALYSIS in types
        assert EntityType.TECHNICAL in types

    def test_analysis_and_comparative(self) -> None:
        """Test ANALYSIS + COMPARATIVE combination."""
        blueprint = (
            BlueprintBuilder("analysis-comparative", "Comparative Analysis Blueprint")
            .with_goal("Compare analysis results")
            .add_entity(ContextEntity.analysis(name="analyst", description="Data analyst"))
            .add_entity(ContextEntity.comparative(name="comparator", description="Result comparator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.ANALYSIS in types
        assert EntityType.COMPARATIVE in types

    def test_analysis_and_educational(self) -> None:
        """Test ANALYSIS + EDUCATIONAL combination."""
        blueprint = (
            BlueprintBuilder("analysis-educational", "Educational Analysis Blueprint")
            .with_goal("Teach analysis methods")
            .add_entity(ContextEntity.analysis(name="analyst", description="Data analyst"))
            .add_entity(ContextEntity.educational(name="teacher", description="Analysis teacher"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.ANALYSIS in types
        assert EntityType.EDUCATIONAL in types

    def test_analysis_and_validation(self) -> None:
        """Test ANALYSIS + VALIDATION combination."""
        blueprint = (
            BlueprintBuilder("analysis-validation", "Validated Analysis Blueprint")
            .with_goal("Validate analysis results")
            .add_entity(ContextEntity.analysis(name="analyst", description="Data analyst"))
            .add_entity(ContextEntity.validation(name="validator", description="Result validator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.ANALYSIS in types
        assert EntityType.VALIDATION in types

    def test_technical_and_comparative(self) -> None:
        """Test TECHNICAL + COMPARATIVE combination."""
        blueprint = (
            BlueprintBuilder("technical-comparative", "Technical Comparison Blueprint")
            .with_goal("Compare technical solutions")
            .add_entity(ContextEntity.technical(name="system1", description="First system"))
            .add_entity(ContextEntity.comparative(name="comparator", description="System comparator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.TECHNICAL in types
        assert EntityType.COMPARATIVE in types

    def test_technical_and_educational(self) -> None:
        """Test TECHNICAL + EDUCATIONAL combination."""
        blueprint = (
            BlueprintBuilder("technical-educational", "Technical Education Blueprint")
            .with_goal("Teach technical concepts")
            .add_entity(ContextEntity.technical(name="system", description="Technical system"))
            .add_entity(ContextEntity.educational(name="teacher", description="Technical teacher"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.TECHNICAL in types
        assert EntityType.EDUCATIONAL in types

    def test_technical_and_validation(self) -> None:
        """Test TECHNICAL + VALIDATION combination."""
        blueprint = (
            BlueprintBuilder("technical-validation", "Technical Validation Blueprint")
            .with_goal("Validate technical implementation")
            .add_entity(ContextEntity.technical(name="system", description="Technical system"))
            .add_entity(ContextEntity.validation(name="validator", description="System validator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.TECHNICAL in types
        assert EntityType.VALIDATION in types

    def test_comparative_and_educational(self) -> None:
        """Test COMPARATIVE + EDUCATIONAL combination."""
        blueprint = (
            BlueprintBuilder("comparative-educational", "Educational Comparison Blueprint")
            .with_goal("Teach comparison methods")
            .add_entity(ContextEntity.comparative(name="comparator", description="Comparison expert"))
            .add_entity(ContextEntity.educational(name="teacher", description="Comparison teacher"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.COMPARATIVE in types
        assert EntityType.EDUCATIONAL in types

    def test_comparative_and_validation(self) -> None:
        """Test COMPARATIVE + VALIDATION combination."""
        blueprint = (
            BlueprintBuilder("comparative-validation", "Validated Comparison Blueprint")
            .with_goal("Validate comparison results")
            .add_entity(ContextEntity.comparative(name="comparator", description="Comparison expert"))
            .add_entity(ContextEntity.validation(name="validator", description="Result validator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.COMPARATIVE in types
        assert EntityType.VALIDATION in types

    def test_educational_and_validation(self) -> None:
        """Test EDUCATIONAL + VALIDATION combination."""
        blueprint = (
            BlueprintBuilder("educational-validation", "Validated Education Blueprint")
            .with_goal("Validate educational content")
            .add_entity(ContextEntity.educational(name="teacher", description="Educator"))
            .add_entity(ContextEntity.validation(name="validator", description="Content validator"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.EDUCATIONAL in types
        assert EntityType.VALIDATION in types


class TestAllEntityTypesTogether:
    """Test blueprints with all entity types combined."""

    def test_all_six_entity_types(self) -> None:
        """Test blueprint with all 6 entity types together."""
        blueprint = (
            BlueprintBuilder("all-entities", "Comprehensive Blueprint")
            .with_goal("Complete comprehensive task using all entity types")
            .add_entity(ContextEntity.content(name="writer", description="Content writer"))
            .add_entity(ContextEntity.analysis(name="analyst", description="Data analyst"))
            .add_entity(ContextEntity.technical(name="engineer", description="Technical engineer"))
            .add_entity(ContextEntity.comparative(name="comparator", description="Comparison expert"))
            .add_entity(ContextEntity.educational(name="teacher", description="Educator"))
            .add_entity(ContextEntity.validation(name="validator", description="Quality validator"))
            .build()
        )

        assert len(blueprint.entities) == 6
        types = {e.entity_type for e in blueprint.entities}
        assert len(types) == 6
        assert EntityType.CONTENT in types
        assert EntityType.ANALYSIS in types
        assert EntityType.TECHNICAL in types
        assert EntityType.COMPARATIVE in types
        assert EntityType.EDUCATIONAL in types
        assert EntityType.VALIDATION in types

        # Verify prompt generation works with all types
        prompt = blueprint.to_prompt()
        assert "Type: Content" in prompt
        assert "Type: Analysis" in prompt
        assert "Type: Technical" in prompt
        assert "Type: Comparative" in prompt
        assert "Type: Educational" in prompt
        assert "Type: Validation" in prompt

    def test_all_entities_prompt_structure(self) -> None:
        """Test that prompt structure is correct with all entity types."""
        blueprint = (
            BlueprintBuilder("prompt-test", "Prompt Structure Test")
            .with_goal("Test prompt generation")
            .add_entity(ContextEntity.content(name="c1", description="Content 1"))
            .add_entity(ContextEntity.analysis(name="a1", description="Analysis 1"))
            .add_entity(ContextEntity.technical(name="t1", description="Technical 1"))
            .add_entity(ContextEntity.comparative(name="comp1", description="Comparative 1"))
            .add_entity(ContextEntity.educational(name="e1", description="Educational 1"))
            .add_entity(ContextEntity.validation(name="v1", description="Validation 1"))
            .build()
        )

        prompt = blueprint.to_prompt()

        # Verify all sections exist
        assert "## Goal" in prompt
        assert "## Context Entities" in prompt

        # Verify all entity names appear
        assert "c1" in prompt
        assert "a1" in prompt
        assert "t1" in prompt
        assert "comp1" in prompt
        assert "e1" in prompt
        assert "v1" in prompt


class TestUseCasePermutations:
    """Test different use case domains with various entity combinations."""

    def test_content_generation_use_case(self) -> None:
        """Test content generation use case with multiple entity types."""
        blueprint = (
            BlueprintBuilder("content-gen", "Content Generation")
            .with_goal("Generate comprehensive article")
            .add_entity(ContextEntity.content(name="writer", style="narrative"))
            .add_entity(ContextEntity.analysis(name="researcher", methodology="qualitative"))
            .add_entity(ContextEntity.validation(name="editor", validation_type="quality"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.CONTENT in types
        assert EntityType.ANALYSIS in types
        assert EntityType.VALIDATION in types

    def test_educational_use_case(self) -> None:
        """Test educational use case with multiple entity types."""
        blueprint = (
            BlueprintBuilder("education", "Educational Content")
            .with_goal("Create educational material")
            .add_entity(ContextEntity.educational(name="teacher", teaching_style="socratic"))
            .add_entity(ContextEntity.content(name="content_creator", style="technical"))
            .add_entity(ContextEntity.comparative(name="comparison_helper", format="side-by-side"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.EDUCATIONAL in types
        assert EntityType.CONTENT in types
        assert EntityType.COMPARATIVE in types

    def test_research_analysis_use_case(self) -> None:
        """Test research/analysis use case with multiple entity types."""
        blueprint = (
            BlueprintBuilder("research", "Research Analysis")
            .with_goal("Conduct comprehensive research")
            .add_entity(ContextEntity.analysis(name="researcher", methodology="mixed"))
            .add_entity(ContextEntity.comparative(name="comparator", format="table"))
            .add_entity(ContextEntity.validation(name="validator", validation_type="quality"))
            .add_entity(ContextEntity.educational(name="explainer", teaching_style="demonstration"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert len(types) == 4
        assert EntityType.ANALYSIS in types
        assert EntityType.COMPARATIVE in types
        assert EntityType.VALIDATION in types
        assert EntityType.EDUCATIONAL in types

    def test_technical_documentation_use_case(self) -> None:
        """Test technical documentation use case with multiple entity types."""
        blueprint = (
            BlueprintBuilder("tech-docs", "Technical Documentation")
            .with_goal("Create technical documentation")
            .add_entity(ContextEntity.technical(name="system", domain="software"))
            .add_entity(ContextEntity.content(name="writer", style="technical"))
            .add_entity(ContextEntity.validation(name="reviewer", validation_type="schema"))
            .add_entity(ContextEntity.educational(name="teacher", knowledge_level="beginner"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.TECHNICAL in types
        assert EntityType.CONTENT in types
        assert EntityType.VALIDATION in types
        assert EntityType.EDUCATIONAL in types

    def test_product_comparison_use_case(self) -> None:
        """Test product comparison use case with multiple entity types."""
        blueprint = (
            BlueprintBuilder("product-comp", "Product Comparison")
            .with_goal("Compare multiple products")
            .add_entity(ContextEntity.comparative(name="comparator", dimensions=("price", "features")))
            .add_entity(ContextEntity.analysis(name="analyst", methodology="quantitative"))
            .add_entity(ContextEntity.content(name="writer", style="persuasive"))
            .add_entity(ContextEntity.validation(name="fact_checker", validation_type="compliance"))
            .build()
        )

        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.COMPARATIVE in types
        assert EntityType.ANALYSIS in types
        assert EntityType.CONTENT in types
        assert EntityType.VALIDATION in types


class TestEmptyAndMinimalBlueprints:
    """Test edge cases: no entities, minimal blueprints."""

    def test_no_entities(self) -> None:
        """Test blueprint with no entities (entities are optional)."""
        blueprint = (
            BlueprintBuilder("no-entities", "Minimal Blueprint")
            .with_goal("Simple task without entities")
            .build()
        )

        assert len(blueprint.entities) == 0
        prompt = blueprint.to_prompt()
        assert "## Goal" in prompt
        assert "## Context Entities" not in prompt  # Should not appear if empty

    def test_single_entity_minimal(self) -> None:
        """Test minimal blueprint with single entity."""
        blueprint = (
            BlueprintBuilder("minimal", "Minimal Blueprint")
            .with_goal("Simple task")
            .add_entity(ContextEntity.content(name="writer"))
            .build()
        )

        assert len(blueprint.entities) == 1
        assert blueprint.entities[0].entity_type == EntityType.CONTENT

    def test_all_entity_types_minimal_config(self) -> None:
        """Test all entity types with minimal configuration."""
        blueprint = (
            BlueprintBuilder("minimal-all", "Minimal All Entities")
            .with_goal("Test minimal configs")
            .add_entity(ContextEntity.content(name="c"))
            .add_entity(ContextEntity.analysis(name="a"))
            .add_entity(ContextEntity.technical(name="t"))
            .add_entity(ContextEntity.comparative(name="comp"))
            .add_entity(ContextEntity.educational(name="e"))
            .add_entity(ContextEntity.validation(name="v"))
            .build()
        )

        assert len(blueprint.entities) == 6
        types = {e.entity_type for e in blueprint.entities}
        assert len(types) == 6

        # Should still generate valid prompt
        prompt = blueprint.to_prompt()
        assert len(prompt) > 0
        assert "## Goal" in prompt


class TestPromptGenerationForAllTypes:
    """Test that prompt generation works correctly for all entity types."""

    def test_prompt_includes_all_entity_metadata(self) -> None:
        """Test that prompt includes type-specific metadata for all entity types."""
        blueprint = (
            BlueprintBuilder("metadata-test", "Metadata Test")
            .with_goal("Test metadata in prompts")
            .add_entity(
                ContextEntity.content(
                    name="writer",
                    style="narrative",
                    perspective="first-person",
                    tone="casual",
                )
            )
            .add_entity(
                ContextEntity.analysis(
                    name="analyst",
                    methodology="quantitative",
                    depth="comprehensive",
                    focus_areas=("trends", "patterns"),
                )
            )
            .add_entity(
                ContextEntity.technical(
                    name="engineer",
                    domain="software",
                    audience_level="advanced",
                    include_code_examples=True,
                )
            )
            .add_entity(
                ContextEntity.comparative(
                    name="comparator",
                    dimensions=("cost", "performance"),
                    format="table",
                    bias_awareness="objective",
                )
            )
            .add_entity(
                ContextEntity.educational(
                    name="teacher",
                    teaching_style="socratic",
                    knowledge_level="beginner",
                    include_examples=True,
                )
            )
            .add_entity(
                ContextEntity.validation(
                    name="validator",
                    validation_type="schema",
                    rules=("rule1", "rule2"),
                    severity_levels=("error", "warning"),
                )
            )
            .build()
        )

        prompt = blueprint.to_prompt()

        # Verify content-specific metadata
        assert "Style: narrative" in prompt or "narrative" in prompt.lower()
        assert "Perspective: first-person" in prompt or "first-person" in prompt.lower()

        # Verify analysis-specific metadata
        assert "Methodology: quantitative" in prompt or "quantitative" in prompt.lower()
        assert "Depth: comprehensive" in prompt or "comprehensive" in prompt.lower()

        # Verify technical-specific metadata
        assert "Domain: software" in prompt or "software" in prompt.lower()
        assert "Audience: advanced" in prompt or "advanced" in prompt.lower()

        # Verify comparative-specific metadata
        assert "Compare on:" in prompt or "dimensions" in prompt.lower()
        assert "Format: table" in prompt or "table" in prompt.lower()

        # Verify educational-specific metadata
        assert "Teaching Style: socratic" in prompt or "socratic" in prompt.lower()
        assert "Student Level: beginner" in prompt or "beginner" in prompt.lower()

        # Verify validation-specific metadata
        assert "Validation Type: schema" in prompt or "schema" in prompt.lower()
        assert "Rules:" in prompt or "rule1" in prompt.lower()
