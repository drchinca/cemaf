"""Lossless OKF context adaptation using CEMAF's token estimator contract."""

from dataclasses import dataclass, field
from typing import Any

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import SimpleTokenEstimator, TokenEstimator
from cemaf.context.source import ContextSource, ContextType
from cemaf.core.types import TokenCount
from cemaf.knowledge.okf import OKFBundle, OKFDocument


@dataclass(frozen=True)
class OKFCatalogPage:
    """One budgeted discovery page, with an explicit continuation offset."""

    source: ContextSource
    next_offset: int | None
    total_entries: int


@dataclass
class OKFAdapter:
    """Adapt a selected concept, never truncating evidence or metadata.

    Discover with ``OKFBundle.catalog`` before selecting documents. If a
    selected concept exceeds its budget, the caller must choose a smaller
    concept or raise the budget. Inject a model tokenizer for exact counts.
    """

    bundle_id: str
    revision: str = ""
    token_estimator: TokenEstimator = field(default_factory=SimpleTokenEstimator)

    async def adapt_catalog(
        self,
        bundle: OKFBundle,
        budget: TokenBudget,
        *,
        directory: str = "",
        offset: int = 0,
        limit: int = 50,
        include_descriptions: bool = True,
        priority: int = 0,
    ) -> OKFCatalogPage:
        """Fit a contiguous page under budget, including its continuation marker.

        No entries are skipped or truncated. If the first entry cannot fit,
        increase the budget or omit descriptions. Pin ``revision`` on this
        adapter to reject pagination against a different snapshot.
        """
        if not self.bundle_id or ":" in self.bundle_id:
            raise ValueError("bundle_id must be non-empty and contain no colon")
        if offset < 0 or limit < 1:
            raise ValueError("Catalog offset must be non-negative and limit must be positive")
        revision = bundle.revision
        if self.revision and self.revision != revision:
            raise ValueError("OKF catalog snapshot changed; restart discovery")
        entries = bundle.catalog_entries(directory, include_descriptions=include_descriptions)
        if offset > len(entries):
            raise ValueError("Catalog offset is beyond the end")
        header = f"# /{directory + '/' if directory else ''}"
        # Test full rendered candidates: tokenizers need not be additive or
        # monotonic, and the continuation marker also consumes budget.
        counts = range(min(limit, len(entries) - offset), 0, -1) if offset < len(entries) else (0,)
        for count in counts:
            end = offset + count
            next_offset = end if end < len(entries) else None
            lines = [header, *entries[offset:end]]
            if next_offset is not None:
                lines.append(f"Next catalog offset: {next_offset}")
            content = "\n".join(lines)
            tokens = self.token_estimator.estimate(content)
            if tokens <= budget.available_tokens:
                return OKFCatalogPage(
                    source=ContextSource(
                        content=content,
                        token_count=TokenCount(tokens),
                        priority=priority,
                        source_type="okf_catalog",
                        source_id=f"okf-catalog:{self.bundle_id}:{directory}:{offset}",
                        compressible=False,
                        context_type=ContextType.RESOURCE,
                        metadata={
                            "bundle_id": self.bundle_id,
                            "bundle_revision": revision,
                            "directory": directory,
                            "offset": offset,
                            "entry_count": count,
                            "next_offset": next_offset,
                            "total_entries": len(entries),
                        },
                    ),
                    next_offset=next_offset,
                    total_entries=len(entries),
                )
        raise ValueError("OKF catalog entry exceeds budget; increase budget or omit descriptions")

    def estimate_tokens(self, data: Any) -> int:
        if not isinstance(data, OKFDocument):
            raise TypeError("OKFAdapter expects an OKFDocument")
        return self.token_estimator.estimate(data.render())

    async def adapt(self, data: Any, budget: TokenBudget, priority: int = 0) -> ContextSource:
        count = self.estimate_tokens(data)
        if count > budget.available_tokens:
            raise ValueError(f"OKF concept needs {count} tokens; budget has {budget.available_tokens}")
        return ContextSource(
            content=data.render(),
            token_count=TokenCount(count),
            priority=priority,
            source_type="okf",
            source_id=data.source_id(bundle_id=self.bundle_id),
            compressible=False,
            metadata=data.metadata(bundle_id=self.bundle_id, revision=self.revision),
            context_type=ContextType.RESOURCE,
        )
