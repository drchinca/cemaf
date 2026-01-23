# Citation Module - Extended Documentation

## Overview

The citation module tracks source attribution for all generated content, enabling transparency, fact-checking, and compliance with content attribution requirements.

**What it does**: Captures citations (source references with URLs, page numbers, access dates) for every piece of information used in generation. Provides storage, query, and formatting for citations in multiple formats (APA, MLA, Chicago). Enables tracing which sources influenced which outputs.

**Key use cases**:
- Attribute sources in published content (journalism, research, education)
- Enable fact-checking by linking claims back to sources
- Comply with creative commons and attribution licenses
- Audit AI generation transparency
- Support reader trust through verifiable references
- Create bibliography from generated content

**When to use vs. alternatives**: Use citations when content references external information and consumers need source verification. Especially critical for news, research, educational content. Don't use for purely original generated content, or when sources are proprietary/confidential.

## Core Concepts

### Citation Hierarchy

**Source**: The original document (article, website, API response, database record). Identified by URL, title, and optionally publication metadata. Sources are immutable and versioned by access timestamp.

**Citation**: A reference to a specific part of a source (page range, section, exact quote). Many citations can point to the same source. Citations track confidence (how certain the reference is correct).

**CitationSpan**: The location in generated content where a citation applies. Can span phrases, sentences, or paragraphs. Enables highlighting citations in UI.

**CitationGroup**: Collections of related citations, useful for organizing complex outputs (one group per section, claim, paragraph).

### Citation Confidence and Accuracy

Each citation has a confidence score (0-1) indicating how certain the attribution is:
- 1.0: Direct quote from source
- 0.8-0.99: Paraphrased from clear source passage
- 0.5-0.79: Inferred from source but not explicitly stated
- 0.3-0.49: Loosely related to source
- < 0.3: Speculative

Confidence drives downstream decisions:
- High confidence (>0.9) can be used in formal citations
- Medium (0.5-0.9) should be flagged for review
- Low (<0.5) should not appear in final citations

### Citation Formats

The module supports multiple output formats:

**APA 7th Edition**: Formal academic citations, alphabetically ordered
**MLA 9th Edition**: Literature citations with hanging indents
**Chicago Manual of Style 17th**: Detailed reference with footnotes
**Rich Text (HTML)**: Inline citations with links and tooltips
**JSON/Structured**: For programmatic use and databases

## Usage Examples

### Capturing Citations During Generation

```python
from cemaf.citation import Citation, Source, CitationManager, CitationFormat
from datetime import datetime, timezone

# Create citation manager
manager = CitationManager()

# Register sources as they're discovered
source = Source(
    url="https://example.com/article",
    title="Article Title",
    authors=["John Doe", "Jane Smith"],
    publication_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
    accessed_at=datetime.now(timezone.utc),
    content_type="article"
)

source = await manager.add_source(source)

# Create citation for specific content
citation = Citation(
    source_id=source.id,
    quote="The exact text from the source",
    confidence=1.0,  # Direct quote
    page_range="23-24"
)

citation = await manager.add_citation(citation)

# Track where in output the citation applies
span = {
    "citation_id": citation.id,
    "start_char": 145,
    "end_char": 180,
    "context": "...the exact text from the source..."
}
```

### Building Citations from Generation Output

```python
from cemaf.citation import CitationBuilder
from cemaf.context.context import Context

# After generation completes
context: Context = generation_result.final_context

# Builder extracts citations from context
builder = CitationBuilder()
citations = await builder.build_from_context(
    context=context,
    generated_content="The full generated article..."
)

# Get citations in various formats
apa_citations = await builder.format_citations(
    citations,
    format=CitationFormat.APA
)

mla_citations = await builder.format_citations(
    citations,
    format=CitationFormat.MLA
)

print("References (APA):")
for ref in apa_citations:
    print(f"  {ref}")
```

### Tracing Claims Back to Sources

```python
from cemaf.citation import CitationManager

manager = CitationManager()

# Given a claim in the output
claim = "Climate change is affecting weather patterns"
claim_position = (200, 250)  # Character positions in output

# Find citations that support this claim
relevant_citations = await manager.find_citations_for_span(
    start_char=claim_position[0],
    end_char=claim_position[1]
)

for citation in relevant_citations:
    source = await manager.get_source(citation.source_id)
    print(f"Claim: '{claim}'")
    print(f"  Source: {source.title} ({source.url})")
    print(f"  Quote: '{citation.quote}'")
    print(f"  Confidence: {citation.confidence:.1%}")
```

### Multiple Citation Formats for Different Contexts

```python
from cemaf.citation import CitationFormat

# Journalism article (need accessible format)
html_citations = await builder.format_citations(
    citations,
    format=CitationFormat.HTML
)
# Output: <a href="...">Source Title</a> (accessed Jan 15)

# Academic paper (need formal APA)
apa_citations = await builder.format_citations(
    citations,
    format=CitationFormat.APA
)
# Output: Author, A. A. (Year). Title. Publisher.

# Web article (need inline citations)
inline_citations = await builder.format_citations(
    citations,
    format=CitationFormat.INLINE
)
# Output: According to Example.com (2024), "quote text"

# Social media (need minimal format)
social_citations = await builder.format_citations(
    citations,
    format=CitationFormat.MINIMAL
)
# Output: via @source_handle
```

### Citation Quality Control

```python
from cemaf.citation import CitationManager, CONFIDENCE_THRESHOLD_HIGH

manager = CitationManager()

# Retrieve all citations
all_citations = await manager.get_citations_for_content(content_id)

# Filter by confidence for publication
high_confidence = [
    c for c in all_citations
    if c.confidence >= CONFIDENCE_THRESHOLD_HIGH
]

low_confidence = [
    c for c in all_citations
    if c.confidence < CONFIDENCE_THRESHOLD_HIGH
]

if low_confidence:
    print(f"⚠️  {len(low_confidence)} low-confidence citations need review:")
    for c in low_confidence:
        source = await manager.get_source(c.source_id)
        print(f"  - {source.title} (confidence: {c.confidence:.1%})")
else:
    print(f"✓ All {len(high_confidence)} citations verified")
```

### Citation Chains (Citation of Citations)

```python
# Handle cases where your source itself cites another
citation = Citation(
    source_id=source.id,
    quote="As Smith argues, '...'",
    confidence=0.8,
    cited_source_id=smith_source.id,  # Smith's source
    citation_type="secondary"
)

# Format as secondary citation
# Smith, J. (2022). Title. Pub. As cited in Example (2024).
```

### Common Mistake: Losing Citation Context

```python
# ❌ WRONG - Citation without context
citation = Citation(
    source_id=source.id,
    quote="some quote"
    # Missing: confidence, page_range, context
)

# ✅ CORRECT - Complete citation metadata
citation = Citation(
    source_id=source.id,
    quote="some quote",
    confidence=0.95,
    page_range="42-43",
    context="Full sentence containing the quote...",
    quoted_by="AI Generator v2.1",
    timestamp=utc_now()
)
```

## Integration

### With Generation Module

```python
from cemaf.generation.protocols import ContentGenerator
from cemaf.citation import CitationManager, CitationBuilder

class CitedContentGenerator:
    """Content generator that tracks citations."""

    def __init__(
        self,
        generator: ContentGenerator,
        citation_manager: CitationManager
    ):
        self.generator = generator
        self.citation_manager = citation_manager

    async def generate_with_citations(self, prompt: str):
        """Generate content and automatically extract citations."""
        # Generate
        result = await self.generator.generate(prompt)

        # Extract citations from context
        builder = CitationBuilder(self.citation_manager)
        citations = await builder.build_from_context(
            context=result.final_context,
            generated_content=result.output
        )

        return {
            "content": result.output,
            "citations": citations
        }
```

### With Context Module

```python
from cemaf.context.context import Context
from cemaf.citation import CitationExtractor

# Context contains sources used during reasoning
context: Context
sources = context.sources  # List of used sources

# Extract citations from context
extractor = CitationExtractor()
citations = await extractor.extract_from_context(context)

# Map sources to their role in reasoning
for source in sources:
    citations_for_source = [
        c for c in citations
        if c.source_id == source.id
    ]
    print(f"{source.url}: {len(citations_for_source)} citations")
```

### With Persistence Module

```python
from cemaf.persistence.entities import ContentItem, ContextArtifact
from cemaf.citation import CitationManager

# Store citations with content
manager = CitationManager()

# Save citations as part of content metadata
content = ContentItem(
    project_id=project.id,
    platform="article",
    format="long_form",
    body=generated_text
)

# Save citations separately, link by content ID
citations = await manager.get_citations_for_content(content_id=content.id)
content = content.model_copy(update={
    "metadata": {
        "citation_count": len(citations),
        "citation_ids": [c.id for c in citations]
    }
})

# Retrieve together
full_content = await retriever.get_content_with_citations(content.id)
```

### With Publishing Module

```python
from cemaf.citation import CitationFormat

# When publishing, include citations in appropriate format
async def publish_with_citations(content_id, platform):
    content = await content_store.get(content_id)
    citations = await citation_manager.get_citations_for_content(content_id)

    # Format citations for platform
    if platform == "twitter":
        # Minimal format with links
        format = CitationFormat.MINIMAL
    elif platform == "academic_article":
        # Full APA citations
        format = CitationFormat.APA
    else:
        # Inline HTML
        format = CitationFormat.HTML

    formatted = await citation_builder.format_citations(citations, format)

    # Include in published content
    await publisher.publish(
        content_text=content.body,
        citations=formatted,
        platform=platform
    )
```

### With Validation Module

```python
from cemaf.validation import ValidationPipeline, Rule

class CitationCoverageRule(Rule):
    """Validate that all claims are cited."""

    async def validate(self, content_item):
        citations = await citation_manager.get_citations_for_content(
            content_item.id
        )

        # Extract claims from content
        claims = await claim_extractor.extract(content_item.body)

        if not claims:
            return None  # No claims, nothing to cite

        # Check coverage
        covered_claims = await self._get_covered_claims(claims, citations)
        coverage = len(covered_claims) / len(claims)

        if coverage < 0.8:  # Want 80%+ coverage
            return ValidationError(
                message=f"Low citation coverage: {coverage:.0%}",
                details=f"{len(claims) - len(covered_claims)} uncited claims"
            )

        return None
```

## API Reference

### Source

```python
@dataclass(frozen=True)
class Source:
    id: str = Field(default_factory=lambda: generate_id("src"))
    url: str
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_date: datetime | None = None
    accessed_at: datetime = Field(default_factory=utc_now)
    content_type: str = "article"  # article, webpage, pdf, api, etc.
    publisher: str | None = None
    description: str | None = None
    metadata: JSON = Field(default_factory=dict)
```

### Citation

```python
@dataclass(frozen=True)
class Citation:
    id: str = Field(default_factory=lambda: generate_id("cit"))
    source_id: str
    quote: str  # Text from source
    confidence: float = 1.0  # 0.0-1.0, certainty of attribution
    page_range: str | None = None
    context: str | None = None  # Surrounding context
    cited_source_id: str | None = None  # Secondary citation
    citation_type: str = "direct"  # direct, secondary, inference
    created_at: datetime = Field(default_factory=utc_now)
    metadata: JSON = Field(default_factory=dict)
```

### CitationSpan

```python
@dataclass
class CitationSpan:
    citation_id: str
    start_char: int  # Position in output text
    end_char: int
    context_before: str = ""
    context_after: str = ""
```

### CitationFormat Enum

```python
class CitationFormat(str, Enum):
    APA = "apa"              # APA 7th edition
    MLA = "mla"              # MLA 9th edition
    CHICAGO = "chicago"      # Chicago style
    HTML = "html"            # HTML with links
    INLINE = "inline"        # Inline text format
    MINIMAL = "minimal"      # Social media minimal
    JSON = "json"            # Structured JSON
```

### CitationManager Protocol

```python
class CitationManager(Protocol):
    async def add_source(self, source: Source) -> Source: ...
    async def get_source(self, source_id: str) -> Source | None: ...
    async def add_citation(self, citation: Citation) -> Citation: ...
    async def get_citation(self, citation_id: str) -> Citation | None: ...
    async def get_citations_for_content(self, content_id: str) -> list[Citation]: ...
    async def get_citations_for_source(self, source_id: str) -> list[Citation]: ...
    async def find_citations_for_span(
        self,
        start_char: int,
        end_char: int
    ) -> list[Citation]: ...
    async def update_citation_confidence(
        self,
        citation_id: str,
        confidence: float
    ) -> Citation: ...

class CitationBuilder(Protocol):
    async def build_from_context(
        self,
        context: Context,
        generated_content: str
    ) -> list[Citation]: ...
    async def format_citations(
        self,
        citations: list[Citation],
        format: CitationFormat
    ) -> list[str]: ...
    async def generate_bibliography(
        self,
        citations: list[Citation],
        format: CitationFormat
    ) -> str: ...
```

## Best Practices

### Citation Confidence Guidelines

```python
# 1.0 - Direct quote
citation = Citation(
    quote="The exact words from the source",
    confidence=1.0
)

# 0.8-0.99 - Clear paraphrase with page number
citation = Citation(
    quote="Summary of source's main point",
    confidence=0.95,
    page_range="42-43"
)

# 0.5-0.79 - Inferred from section but not explicit
citation = Citation(
    quote="Related concept drawn from source context",
    confidence=0.7
)

# <0.5 - Speculative, needs human review
citation = Citation(
    quote="Tangentially related concept",
    confidence=0.3
)
```

### Performance Tips

- **Batch source lookups**: Don't lookup source by ID one at a time
- **Cache formatted citations**: Once formatted for a platform, cache the result
- **Lazy extract**: Don't extract all citations upfront. Extract only for published content.
- **Index by confidence**: For UI filtering, index on confidence level

### Common Pitfalls

**Losing source context**: Always save which part of the source supported which claim. Without position, citations are useless.

**Inflated confidence scores**: Resist temptation to mark everything as high confidence. Be honest about uncertainty. If you inferred something, mark it as such.

**Broken links**: Verify source URLs are still valid. Store archived URLs as fallback.

**Missing metadata**: Include publication date, authors, publisher. They matter for credibility assessment.

**Forgetting secondary citations**: When your source cites another, mark it as secondary. Readers need to know the chain.

### When NOT to Use

- **Proprietary data**: Don't cite internal/confidential sources
- **Real-time data**: Don't cite data that changes frequently without versioning
- **Generated content**: Don't cite LLM-generated text as a source
- **Personal communications**: Be careful with hearsay and rumors as sources

### Validation Strategy

```python
# Before publishing, validate citations
async def validate_citations(content_id, citations):
    issues = []

    for citation in citations:
        source = await manager.get_source(citation.source_id)

        # Check 1: Source is accessible
        if not await is_url_accessible(source.url):
            issues.append(f"Source unreachable: {source.url}")

        # Check 2: Quote appears in source
        if not await quote_found_in_source(citation.quote, source):
            issues.append(f"Quote not found in source: {citation.quote}")

        # Check 3: Low confidence citations are flagged
        if citation.confidence < 0.7:
            issues.append(f"Low confidence citation: {citation.quote}")

        # Check 4: All claims are cited
        covered = await has_supporting_citations(content_id)
        if not covered:
            issues.append("Uncited claims detected")

    return issues
```

### Citation Quality Score

```python
def calculate_citation_quality(citations: list[Citation]) -> float:
    """Score quality of citation coverage (0-1)."""
    if not citations:
        return 0.0

    # Factors:
    high_confidence = sum(1 for c in citations if c.confidence >= 0.9)
    with_sources = sum(1 for c in citations if c.source_id)
    with_pages = sum(1 for c in citations if c.page_range)

    score = (
        (high_confidence / len(citations)) * 0.5 +  # Confidence weight
        (with_sources / len(citations)) * 0.3 +      # Completeness
        (with_pages / len(citations)) * 0.2          # Precision
    )

    return min(1.0, score)
```
