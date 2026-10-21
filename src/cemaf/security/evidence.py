"""Authorized evidence views with explicit redaction and separate view identity."""

from __future__ import annotations

import json

from cemaf.context.manifest import ContentDigest, canonical_json
from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import MemoryScope
from cemaf.memory.base import MemoryItem
from cemaf.persistence.artifacts import ArtifactAccessDeniedError, ArtifactResolver
from cemaf.persistence.evidence import RecordedEvidence
from cemaf.security.masking import MaskingPipeline, MaskingRule, MaskingStrategy


async def export_evidence_view(
    *,
    record: RecordedEvidence,
    registry: ArtifactResolver,
    principal_id: str,
    clearance: SecurityLevel,
    masking: MaskingPipeline | None = None,
) -> dict[str, object]:
    """Reauthorize every disclosed source; redact free-form fields if any access is denied.

    Default export is metadata-only. Explicit masking policy can allow content.
    Request/response bodies are withheld whenever evidence is denied because
    they can transitively contain protected text or identifiers.
    """
    pipeline = masking or MaskingPipeline(
        [
            MaskingRule(field=field, strategy=MaskingStrategy.MASK)
            for field in ("request", "response", "content")
        ]
    )
    evidence: list[dict[str, object]] = []
    redactions: set[str] = set()
    denied = False
    for ref in record.request.context.artifact_refs:
        try:
            # A readable summary cannot disclose a parent whose access was revoked.
            for ancestor in record.request.context.required_refs((ref.source_id,)):
                if ancestor.source_id != ref.source_id:
                    await registry.resolve(ref=ancestor, principal_id=principal_id, clearance=clearance)
            content = (
                await registry.resolve(ref=ref, principal_id=principal_id, clearance=clearance)
            ).decode("utf-8")
        except ArtifactAccessDeniedError:
            denied = True
            redactions.add("restricted_evidence")
            continue
        original = {"content": content}
        masked = pipeline.apply(MemoryItem(scope=MemoryScope.SESSION, key="export", value=original)).value
        if masked != original:
            redactions.add("evidence.content")
        evidence.append({"source_id": ref.source_id, "digest": ref.digest.digest, **masked})
    freeform = (
        {}
        if denied
        else {
            "request": json.loads(record.request.request_json),
            "response": json.loads(record.response_json),
        }
    )
    masked_freeform = pipeline.apply(
        MemoryItem(scope=MemoryScope.SESSION, key="export", value=freeform)
    ).value
    for key in ("request", "response"):
        if denied or masked_freeform.get(key) != freeform.get(key):
            redactions.add(key)
    payload: dict[str, object] = {
        "schema_version": "cemaf.evidence-view.v1",
        "original_evidence_id": record.evidence_id,
        "original_request_id": record.request.request_id,
        "evidence": evidence,
        "redactions": sorted(redactions),
        **masked_freeform,
    }
    payload["view_id"] = ContentDigest.of(canonical_json(payload).encode()).digest
    return payload
