"""LLM protocol decorator enforcing versioned evidence at the dispatch boundary."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from dataclasses import replace

from cemaf.context.compiler import CompiledContext
from cemaf.context.manifest import (
    ContentDigest,
    ContextManifest,
    ExcludedContextRef,
    RequestManifest,
    WorkingContextReceipt,
    canonical_json,
)
from cemaf.context.patch import SecurityLevel
from cemaf.core.types import FinishReason, TokenCount
from cemaf.llm.preflight import RequestTokenCounter, preflight_request
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.budget_guard import check_runtime_budget
from cemaf.persistence.artifacts import ArtifactResolver
from cemaf.persistence.evidence import EvidenceStore, RecordedEvidence


class EvidenceLLMClient:
    """A request-scoped evidence boundary; compose inside the instrumented client.

    The application supplies a manifest and compiler output. Every selected
    excerpt is checked against its complete immutable snapshot; summary parents
    are also reauthorized. This first slice accepts complete text snapshots.
    Arbitrary byte-range and bulk-object adapters remain outside its scope.
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        registry: ArtifactResolver,
        store: EvidenceStore,
        counter: RequestTokenCounter,
        context: ContextManifest,
        compiled: CompiledContext,
        principal_id: str,
        clearance: SecurityLevel,
        policy_version: str,
        context_window: int,
        compiler_version: str = "1",
        node_id: str = "",
        require_exact: bool = True,
    ) -> None:
        self._client, self.registry, self.store, self.counter = client, registry, store, counter
        self.context, self.compiled = context, compiled
        self.principal_id, self.clearance = principal_id, clearance
        self.policy_version, self.context_window = policy_version, context_window
        self.compiler_version, self.node_id, self.require_exact = compiler_version, node_id, require_exact

    @property
    def config(self) -> LLMConfig:
        return self._client.config

    async def _verify(self, messages: list[Message]) -> None:
        selected = tuple(source.source_id for source in self.compiled.sources)
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("Evidence calls require unique selected sources")
        snapshots: dict[str, str] = {}
        for ref in self.context.required_refs(selected):
            snapshots[ref.source_id] = (
                await self.registry.resolve(
                    ref=ref,
                    principal_id=self.principal_id,
                    clearance=self.clearance,
                )
            ).decode("utf-8")
        expected = {source.source_id: source.content for source in self.compiled.sources}
        if any(snapshots[source_id] != text for source_id, text in expected.items()):
            raise ValueError("Compiler evidence differs from the pinned snapshot")
        found: list[str] = []
        for message in messages:
            if message.metadata.get("trust") != "untrusted_evidence":
                continue
            source_id = str(message.metadata.get("source_id", ""))
            if message.role != MessageRole.USER or source_id not in expected:
                raise ValueError("Retrieved evidence must remain in its declared untrusted boundary")
            if message.content != canonical_json({"source_id": source_id, "text": expected[source_id]}):
                raise ValueError("Rendered evidence does not match its pinned excerpt")
            found.append(source_id)
        if tuple(found) != selected:
            raise ValueError("Rendered evidence order differs from compiler selection")

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        # Snapshot mutable caller inputs before the first await.
        messages = [Message.from_dict(json.loads(canonical_json(message.to_dict()))) for message in messages]
        config = (config_override or self.config).model_copy(deep=True)
        tools = copy.deepcopy(tools or [])
        await self._verify(messages)
        preflight = await preflight_request(
            client=self._client,
            counter=self.counter,
            messages=messages,
            tools=tools,
            config=config,
            context_window=self.context_window,
            require_exact=self.require_exact,
        )
        # Revocation or replacement during counting must take effect before dispatch.
        await self._verify(messages)
        receipt = WorkingContextReceipt(
            tenant_id=self.context.tenant_id,
            task_id=self.context.task_id,
            node_id=self.node_id,
            manifest_id=self.context.manifest_id,
            manifest_hash=self.context.content_hash,
            compiler_id="cemaf.context",
            compiler_version=self.compiler_version,
            policy_version=self.policy_version,
            selected_ref_ids=tuple(source.source_id for source in self.compiled.sources),
            excluded=tuple(
                ExcludedContextRef(ref_id=str(item["source_id"]), reason=str(item["reason"]))
                for item in self.compiled.metadata.get("excluded_details", [])
            )
            + tuple(
                ExcludedContextRef(ref_id=str(source_id), reason="security")
                for source_id in self.compiled.metadata.get("security_excluded", [])
            ),
            token_budget=preflight.context_window - preflight.reserved_output_tokens,
            actual_tokens=preflight.count.input_tokens if preflight.count.exact else 0,
            estimated_tokens=preflight.estimated_input_tokens,
            token_count_exact=preflight.count.exact,
            rendered_content_hash=ContentDigest.of(
                canonical_json([message.to_dict() for message in messages]).encode()
            ),
        )
        manifest = RequestManifest.create(
            context=self.context,
            receipt=receipt,
            messages=messages,
            tools=tools,
            config=config,
            authorization_version=self.registry.authorization_version,
        )
        check_runtime_budget()
        result = await self._client.complete(
            messages=messages,
            tools=tools or None,
            config_override=config,
            fidelity=fidelity,
            token_budget=token_budget,
            correlation_id=correlation_id,
        )
        if any(call.name not in {tool.name for tool in tools} for call in result.tool_calls):
            result = replace(result, success=False, error="Model requested an unauthorized tool capability")
        if result.finish_reason not in {FinishReason.TERMINAL_STOP, FinishReason.TERMINAL_TOOL}:
            result = replace(
                result, success=False, error=result.error or "Provider returned incomplete output"
            )
        if int(result.prompt_tokens) + config.max_tokens > self.context_window:
            result = replace(
                result, success=False, error="Provider-reported input exceeded preflight allowance"
            )
        record = RecordedEvidence(
            request=manifest,
            preflight=preflight.model_copy(
                update={"provider_reported_input_tokens": int(result.prompt_tokens)}
            ),
            response_json=canonical_json(
                {
                    "success": result.success,
                    "message": result.message.to_dict() if result.message else None,
                    "error": result.error,
                    "model": result.model or config.model,
                    "prompt_tokens": int(result.prompt_tokens),
                    "completion_tokens": int(result.completion_tokens),
                    "finish_reason": result.finish_reason.value,
                    "finish_reason_native": result.finish_reason_native,
                    "provider": result.provider.value,
                    "metadata": result.metadata,
                }
            ),
        )
        evidence_id = self.store.save(record)
        if result.message is not None:
            result = replace(
                result,
                message=replace(
                    result.message,
                    metadata={
                        **result.message.metadata,
                        "evidence_id": evidence_id,
                        "request_id": manifest.request_id,
                    },
                ),
            )
        return result

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Buffer one completion so unvalidated partial output cannot escape the gate."""
        result = await self.complete(messages=messages, tools=tools, config_override=config_override)
        yield StreamChunk(
            content=str(result.content) if result.success else "",
            is_final=True,
            finish_reason=result.finish_reason if result.success else FinishReason.PARTIAL_ERROR,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            metadata={
                "success": result.success,
                "error": result.error,
                **(result.message.metadata if result.message else {}),
            },
        )

    def count_tokens(self, text: str) -> TokenCount:
        return self._client.count_tokens(text)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        return self._client.count_messages_tokens(messages)

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        return await self._client.count_tokens_exact(messages=messages, tools=tools)
