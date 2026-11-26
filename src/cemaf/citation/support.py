"""Claim support is a separate, pluggable verdict from source membership."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from cemaf.citation.models import CitedFact
from cemaf.core.types import JSON
from cemaf.evals.protocols import BaseEvaluator, EvalMetric, EvalResult


class SupportVerdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"


@runtime_checkable
class ClaimSupportVerifier(Protocol):
    async def verify(self, *, fact: CitedFact, sources: Mapping[str, str]) -> SupportVerdict: ...


class ExactQuoteVerifier:
    """Conservative extractive support; paraphrases remain unverified.

    This proves a quote is in the supplied evidence, not that the source itself
    is true. Apps may inject an independently evaluated domain or semantic
    verifier through the same public port.
    """

    async def verify(self, *, fact: CitedFact, sources: Mapping[str, str]) -> SupportVerdict:
        if not fact.fact.strip() or not fact.citations:
            return SupportVerdict.UNSUPPORTED
        for citation in fact.citations:
            source = sources.get(citation.source_id)
            if (
                source is None
                or not citation.quote
                or citation.quote not in source
                or fact.fact != citation.quote
            ):
                return SupportVerdict.UNSUPPORTED
        return SupportVerdict.SUPPORTED


class ClaimSupportEvaluator(BaseEvaluator):
    """Gate structured claims; publish only the checked claim text.

    The answer must equal the newline-joined claims. This prevents an unchecked
    free-form answer or an extra uncited assertion from riding alongside valid
    citations. Empty, malformed, or omitted claims fail closed.
    """

    def __init__(self, *, verifier: ClaimSupportVerifier, sources: Mapping[str, str]) -> None:
        super().__init__()
        self.verifier, self.sources = verifier, dict(sources)

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.GROUNDEDNESS

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        try:
            if isinstance(output, str):
                output = json.loads(output)
            if not isinstance(output, dict) or not isinstance(output.get("claims"), list):
                raise ValueError("Expected structured claims")
            facts = [CitedFact.from_dict(item) for item in output["claims"]]
            if not facts or output.get("answer") != "\n".join(fact.fact for fact in facts):
                raise ValueError("Answer contains unchecked claims")
            verdicts = [await self.verifier.verify(fact=fact, sources=self.sources) for fact in facts]
        except (KeyError, TypeError, ValueError):
            return self._make_result(score=0.0, reason="Missing or malformed claim evidence")
        supported = sum(verdict == SupportVerdict.SUPPORTED for verdict in verdicts)
        # All claims are required; partial support cannot meet the default threshold.
        return self._make_result(
            score=float(supported == len(facts)),
            reason=", ".join(verdict.value for verdict in verdicts),
            actual=output,
        )
