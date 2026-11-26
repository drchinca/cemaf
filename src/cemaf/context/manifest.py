"""Versioned context references and ordered per-call evidence (SPEC-17 pilot slice).

Canonical JSON strings keep nested request inputs immutable. Hashes identify
recorded input; they do not promise deterministic fresh model output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cemaf.context.compiler import CompiledContext
from cemaf.context.patch import SecurityLevel
from cemaf.core.utils import utc_now
from cemaf.llm.protocols import LLMConfig, Message, ToolDefinition


def canonical_json(value: Any) -> str:
    """Serialize JSON without silently accepting nonfinite values or unknown objects."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContentDigest(ImmutableModel):
    algorithm: str = "sha256"
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_algorithm(self) -> ContentDigest:
        if self.algorithm != "sha256":
            raise ValueError("Unsupported digest algorithm")
        return self

    @classmethod
    def of(cls, content: bytes) -> ContentDigest:
        return cls(digest=hashlib.sha256(content).hexdigest())


class ArtifactRef(ImmutableModel):
    tenant_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    locator: str
    digest: ContentDigest
    immutable_snapshot_id: str | None = None
    logical_bytes: int = Field(ge=0)
    media_type: str = "text/plain; charset=utf-8"
    schema_ref: str | None = None
    security_level: SecurityLevel = SecurityLevel.INTERNAL
    created_at: datetime = Field(default_factory=utc_now)
    metadata: tuple[tuple[str, str], ...] = ()

    @property
    def source_id(self) -> str:
        # A structured encoding avoids delimiter collisions in tenant/id/version.
        return canonical_json([self.tenant_id, self.artifact_id, self.version])


class SourceDependency(ImmutableModel):
    source_id: str
    parent_source_ids: tuple[str, ...]


class ContextManifest(ImmutableModel):
    tenant_id: str
    task_id: str
    manifest_id: str
    version: int = Field(default=1, ge=1)
    parent_manifest_id: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = Field(max_length=256)
    patch_ids: tuple[str, ...] = ()
    logical_bytes: int = Field(ge=0)
    compiler_compatibility: str = "cemaf.context.v1"
    created_at: datetime = Field(default_factory=utc_now)
    dependencies: tuple[SourceDependency, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> ContextManifest:
        ids = [ref.source_id for ref in self.artifact_refs]
        if len(set(ids)) != len(ids) or any(ref.tenant_id != self.tenant_id for ref in self.artifact_refs):
            raise ValueError("Manifest references must be unique and tenant-local")
        if self.logical_bytes != sum(ref.logical_bytes for ref in self.artifact_refs):
            raise ValueError("Logical byte count does not match references")
        graph: dict[str, tuple[str, ...]] = {}
        for dependency in self.dependencies:
            if dependency.source_id in graph or not {
                dependency.source_id,
                *dependency.parent_source_ids,
            } <= set(ids):
                raise ValueError("Dependencies must resolve to unique manifest references")
            graph[dependency.source_id] = dependency.parent_source_ids

        visited: set[str] = set()

        def visit(source_id: str, path: frozenset[str]) -> None:
            if source_id in path:
                raise ValueError("Cyclic evidence dependency")
            if source_id in visited:
                return
            for parent in graph.get(source_id, ()):
                visit(parent, path | {source_id})
            visited.add(source_id)

        for source_id in graph:
            visit(source_id, frozenset())
        return self

    @property
    def content_hash(self) -> ContentDigest:
        return ContentDigest.of(canonical_json(self.model_dump(mode="json")).encode())

    def required_refs(self, selected: tuple[str, ...]) -> tuple[ArtifactRef, ...]:
        refs = {ref.source_id: ref for ref in self.artifact_refs}
        graph = {item.source_id: item.parent_source_ids for item in self.dependencies}
        required: set[str] = set()

        def visit(source_id: str) -> None:
            if source_id not in refs:
                raise ValueError("Selected evidence is absent from manifest")
            if source_id in required:
                return
            required.add(source_id)
            for parent in graph.get(source_id, ()):
                visit(parent)

        for source_id in selected:
            visit(source_id)
        return tuple(ref for ref in self.artifact_refs if ref.source_id in required)


class ExcludedContextRef(ImmutableModel):
    ref_id: str
    reason: str


class WorkingContextReceipt(ImmutableModel):
    tenant_id: str
    task_id: str
    node_id: str
    manifest_id: str
    manifest_hash: ContentDigest
    compiler_id: str
    compiler_version: str
    policy_version: str
    selected_ref_ids: tuple[str, ...]
    excluded: tuple[ExcludedContextRef, ...] = ()
    token_budget: int = Field(ge=0)
    actual_tokens: int = Field(ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    token_count_exact: bool = True
    rendered_content_hash: ContentDigest
    created_at: datetime = Field(default_factory=utc_now)


class RequestManifest(ImmutableModel):
    schema_version: str = "cemaf.request-evidence.v1"
    context: ContextManifest
    receipt: WorkingContextReceipt
    request_json: str = Field(max_length=1_000_000)
    authorization_version: str

    @model_validator(mode="after")
    def validate_input(self) -> RequestManifest:
        if self.schema_version != "cemaf.request-evidence.v1":
            raise ValueError("Unsupported request evidence schema")
        if self.receipt.manifest_hash != self.context.content_hash:
            raise ValueError("Receipt does not identify this context manifest")
        if (self.receipt.tenant_id, self.receipt.task_id, self.receipt.manifest_id) != (
            self.context.tenant_id,
            self.context.task_id,
            self.context.manifest_id,
        ):
            raise ValueError("Receipt identity mismatch")
        payload = json.loads(self.request_json)
        if self.request_json != canonical_json(payload) or set(payload) != {"messages", "tools", "config"}:
            raise ValueError("Request must contain canonical messages, tools, and config")
        if self.receipt.rendered_content_hash != ContentDigest.of(
            canonical_json(payload["messages"]).encode()
        ):
            raise ValueError("Rendered message digest mismatch")
        self.context.required_refs(self.receipt.selected_ref_ids)
        selected = set(self.receipt.selected_ref_ids)
        excluded = {item.ref_id for item in self.receipt.excluded}
        if len(selected) != len(self.receipt.selected_ref_ids) or selected & excluded:
            raise ValueError("Selected and excluded evidence must be distinct")
        if self.receipt.actual_tokens > self.receipt.token_budget:
            raise ValueError("Receipt exceeds its input allowance")
        return self

    @property
    def request_id(self) -> str:
        return ContentDigest.of(canonical_json(self.model_dump(mode="json")).encode()).digest

    @classmethod
    def create(
        cls,
        *,
        context: ContextManifest,
        receipt: WorkingContextReceipt,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: LLMConfig,
        authorization_version: str,
    ) -> RequestManifest:
        return cls(
            context=context,
            receipt=receipt,
            authorization_version=authorization_version,
            request_json=canonical_json(
                {
                    "messages": [message.to_dict() for message in messages],
                    "tools": [asdict(tool) for tool in tools or []],
                    "config": config.model_dump(mode="json"),
                }
            ),
        )


def render_evidence_messages(compiled: CompiledContext) -> list[Message]:
    """Keep retrieved text in user evidence, outside trusted system instructions.

    This is a recorded trust boundary, not a claim that a prompt alone prevents
    injection. Authorization, tool capability checks, and publication gates
    must remain outside the model.
    """
    return [
        Message.user(
            canonical_json({"source_id": source.source_id, "text": source.content}),
            metadata={"trust": "untrusted_evidence", "source_id": source.source_id},
        )
        for source in compiled.sources
    ]
