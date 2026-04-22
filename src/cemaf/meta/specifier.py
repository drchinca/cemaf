"""MetaSpecifier — produces OpenSpec change proposals from feature descriptions."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.types import AgentID
from cemaf.llm.protocols import LLMClient, Message
from cemaf.mcp.bridges.openspec.parser import parse_diagnostics
from cemaf.mcp.bridges.openspec.protocols import (
    DiagnosticSeverity,
    OpenSpecDiagnostic,
    OpenSpecRuntime,
    ValidationReport,
)
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.meta.goals import (
    CapabilityDelta,
    ProposalDoc,
    Requirement,
    Scenario,
    SpecGoal,
    SpecResult,
)

logger = logging.getLogger(__name__)

DEFAULT_VALIDATE_TIMEOUT = 30.0


def render_proposal(*, doc: ProposalDoc) -> Mapping[str, str]:
    """Render a ProposalDoc to the file map an OpenSpec workspace expects.

    Deterministic — same input produces byte-equal output every time.
    """
    files: dict[str, str] = {
        "proposal.md": _render_proposal_md(doc=doc),
        "tasks.md": _render_tasks_md(doc=doc),
    }
    for delta in doc.deltas:
        files[f"specs/{delta.capability}/spec.md"] = _render_spec_md(delta=delta)
    return files


def _render_proposal_md(*, doc: ProposalDoc) -> str:
    lines: list[str] = [f"# {doc.title}", "", "## Why", "", doc.why.strip(), ""]
    if doc.what_changes:
        lines.extend(["## What Changes", ""])
        lines.extend(f"- {item}" for item in doc.what_changes)
        lines.append("")
    if doc.impact:
        lines.extend(["## Impact", ""])
        lines.extend(f"- {item}" for item in doc.impact)
        lines.append("")
    return "\n".join(lines)


def _render_tasks_md(*, doc: ProposalDoc) -> str:
    lines: list[str] = ["# Tasks", ""]
    for task in doc.tasks:
        lines.append(f"- [ ] {task}")
    if not doc.tasks:
        lines.append("- [ ] Define concrete tasks")
    lines.append("")
    return "\n".join(lines)


def _render_spec_md(*, delta: CapabilityDelta) -> str:
    lines: list[str] = [f"# {delta.capability} capability", "", "## ADDED Requirements", ""]
    for req in delta.added_requirements:
        lines.extend([f"### Requirement: {req.name}", "", req.statement.strip(), ""])
        for scenario in req.scenarios:
            lines.extend([f"#### Scenario: {scenario.name}", ""])
            for clause in scenario.given:
                lines.append(f"- **GIVEN** {clause}")
            for clause in scenario.when:
                lines.append(f"- **WHEN** {clause}")
            for clause in scenario.then:
                lines.append(f"- **THEN** {clause}")
            lines.append("")
    return "\n".join(lines)


def template_proposal(*, goal: SpecGoal) -> ProposalDoc:
    """Deterministic fallback proposal used when no LLMClient is available.

    Structurally valid OpenSpec markdown — just not semantically rich. Lets
    the pipeline run end-to-end in tests and offline environments.
    """
    capabilities = goal.capabilities or ("unspecified",)
    deltas = tuple(
        CapabilityDelta(
            capability=cap,
            added_requirements=(
                Requirement(
                    name=f"{cap} placeholder requirement",
                    statement=(
                        f"The {cap} capability SHALL satisfy the intent described in the feature: "
                        f"{goal.feature_description}."
                    ),
                    scenarios=(
                        Scenario(
                            name=f"{cap} baseline scenario",
                            given=(f"the {cap} capability is initialized",),
                            when=("the feature is invoked as described in the proposal",),
                            then=("the documented outcome is observed",),
                        ),
                    ),
                ),
            ),
        )
        for cap in capabilities
    )
    return ProposalDoc(
        change_id=goal.change_id,
        title=goal.change_id.replace("-", " ").title(),
        why=goal.feature_description,
        what_changes=(f"Introduce {goal.change_id}",),
        impact=(f"Affected capabilities: {', '.join(capabilities)}",),
        tasks=("Implement the feature", "Write tests", "Update documentation"),
        deltas=deltas,
    )


class MetaSpecifier(Agent[SpecGoal, SpecResult]):
    """Author an OpenSpec change proposal, render it, and validate via the bridge.

    The agent never touches the filesystem directly. All writes go through
    OpenSpecWorkspace; all validation goes through OpenSpecRuntime.
    """

    def __init__(
        self,
        *,
        workspace: OpenSpecWorkspace,
        runtime: OpenSpecRuntime | None = None,
        llm_client: LLMClient | None = None,
        validate_timeout: float = DEFAULT_VALIDATE_TIMEOUT,
        max_repairs: int = 1,
        system_prompt: str = "",
    ) -> None:
        self._workspace = workspace
        self._runtime = runtime
        self._llm_client = llm_client
        self._validate_timeout = validate_timeout
        self._max_repairs = max_repairs
        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT

    @property
    def id(self) -> AgentID:
        return AgentID("MetaSpecifier")

    @property
    def description(self) -> str:
        return "Authors OpenSpec change proposals from feature descriptions and validates them."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: SpecGoal,
        context: AgentContext,
    ) -> AgentResult[SpecResult]:
        logger.info("[MetaSpecifier] authoring change_id=%s", goal.change_id)
        state = AgentState()
        try:
            proposal = await self._author_proposal(goal=goal)
            validation = await self._write_and_validate(proposal=proposal)
            attempts = 0
            while not validation.passed and attempts < self._max_repairs and self._llm_client is not None:
                attempts += 1
                logger.info(
                    "[MetaSpecifier] repair attempt %d/%d for change_id=%s",
                    attempts,
                    self._max_repairs,
                    goal.change_id,
                )
                proposal = await self._repair_proposal(
                    goal=goal, previous=proposal, diagnostics=validation.diagnostics
                )
                validation = await self._write_and_validate(proposal=proposal)

            rendered = render_proposal(doc=proposal)
            result = SpecResult(
                change_id=goal.change_id,
                proposal=proposal,
                rendered_files=dict(rendered),
                validation_passed=validation.passed,
                diagnostics=tuple(_diagnostic_to_dict(d=d) for d in validation.diagnostics),
                runtime=self._runtime.display_name if self._runtime is not None else "",
            )
            return AgentResult.ok(output=result, state=state)
        except asyncio.CancelledError:
            raise
        except (RuntimeError, ValueError, OSError, TimeoutError, ValidationError) as exc:
            logger.exception("[MetaSpecifier] failed")
            return AgentResult.fail(error=str(exc), state=state)

    async def _author_proposal(self, *, goal: SpecGoal) -> ProposalDoc:
        if self._llm_client is None:
            return template_proposal(goal=goal)
        return await self._llm_proposal(goal=goal)

    async def _repair_proposal(
        self,
        *,
        goal: SpecGoal,
        previous: ProposalDoc,
        diagnostics: tuple[OpenSpecDiagnostic, ...],
    ) -> ProposalDoc:
        if self._llm_client is None:
            return previous
        # Re-author from scratch with diagnostic feedback — sending the full
        # previous doc back would double the prompt every iteration. The model
        # gets the original goal + the validation errors and starts fresh.
        return await self._llm_proposal(goal=goal, diagnostics=diagnostics)

    async def _llm_proposal(
        self,
        *,
        goal: SpecGoal,
        diagnostics: tuple[OpenSpecDiagnostic, ...] = (),
    ) -> ProposalDoc:
        if self._llm_client is None:
            raise RuntimeError("LLM client is required for _llm_proposal")
        prompt = _build_prompt(goal=goal, diagnostics=diagnostics)
        completion = await self._llm_client.complete(
            messages=[
                Message.system(content=self._system_prompt),
                Message.user(content=prompt),
            ],
        )
        if not completion.success or completion.message is None:
            raise RuntimeError(completion.error or "LLM completion failed")
        raw = _extract_text(message=completion.message)
        try:
            payload = _extract_json(text=raw)
        except RuntimeError:
            logger.warning("[MetaSpecifier] LLM output failed JSON extraction: %s", raw[:500])
            raise
        try:
            return ProposalDoc.model_validate(payload)
        except ValidationError as exc:
            logger.warning("[MetaSpecifier] LLM output failed ProposalDoc schema: %s", raw[:500])
            raise RuntimeError(f"LLM output did not match ProposalDoc schema: {exc}") from exc

    async def _write_and_validate(self, *, proposal: ProposalDoc) -> ValidationReport:
        files = render_proposal(doc=proposal)
        await self._workspace.write_change(change_id=proposal.change_id, files=files)
        if self._runtime is None:
            # Honest signal: we wrote files but cannot prove they validate.
            return ValidationReport(
                change_id=proposal.change_id,
                strict=True,
                exit_code=-1,
                diagnostics=(
                    OpenSpecDiagnostic(
                        severity=DiagnosticSeverity.ERROR,
                        message="No OpenSpecRuntime configured — validation skipped",
                        code="runtime-missing",
                    ),
                ),
                raw_output="",
            )
        sub = await self._runtime.execute(
            args=("validate", proposal.change_id, "--strict"),
            cwd=self._workspace.root,
            timeout=self._validate_timeout,
        )
        diagnostics = parse_diagnostics(stdout=sub.text_stdout(), stderr=sub.text_stderr())
        return ValidationReport(
            change_id=proposal.change_id,
            strict=True,
            exit_code=sub.returncode,
            diagnostics=diagnostics,
            raw_output=sub.text_stdout() + sub.text_stderr(),
        )


_DEFAULT_SYSTEM_PROMPT = (
    "You are MetaSpecifier, a CEMAF meta-agent that authors OpenSpec change proposals. "
    "Respond with ONLY a JSON object matching the ProposalDoc schema. "
    "Every capability must have at least one requirement; every requirement at least one scenario. "
    "Each scenario must include at least one GIVEN, WHEN, and THEN clause. "
    "Do not include markdown; JSON only."
)


def _build_prompt(
    *,
    goal: SpecGoal,
    diagnostics: tuple[OpenSpecDiagnostic, ...],
) -> str:
    lines: list[str] = [
        f"change_id: {goal.change_id}",
        f"capabilities: {', '.join(goal.capabilities) or '<choose appropriate names>'}",
        "",
        "Feature description:",
        goal.feature_description,
    ]
    if goal.constraints:
        lines.extend(["", "Constraints:", json.dumps(goal.constraints, indent=2)])
    if diagnostics:
        error_msgs = [d.message for d in diagnostics if d.severity is DiagnosticSeverity.ERROR]
        if error_msgs:
            lines.extend(["", "Previous attempt failed validation. Fix these errors:"])
            lines.extend(f"- {msg}" for msg in error_msgs)
    return "\n".join(lines)


def _extract_text(*, message: Message) -> str:
    """Extract text from a Message, handling Anthropic-shaped content blocks.

    Anthropic content blocks are dicts with shape {"type": "text", "text": str}.
    Tool-use blocks (`type=="tool_use"`) are skipped, not silently consumed.
    """
    content = message.content
    if isinstance(content, str):
        return content
    chunks: list[str] = []
    for block in content:
        if block.get("type") == "text":
            text_value = block.get("text")
            if isinstance(text_value, str):
                chunks.append(text_value)
    return "".join(chunks)


def _extract_json(*, text: str) -> Any:
    """Find and decode the first balanced JSON object in `text`.

    Walks the string with explicit brace-depth + string-state tracking so
    fences (```json), preamble ("Here is the JSON:"), and trailing prose
    are all tolerated. Rejects fenced markdown by simply ignoring it — the
    walker only sees the braces.
    """
    start = text.find("{")
    if start == -1:
        raise RuntimeError("No JSON object found in LLM output")
    depth = 0
    in_string = False
    escape_next = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                payload = text[start : index + 1]
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Could not decode JSON from LLM output: {exc}") from exc
    raise RuntimeError("Unbalanced JSON object in LLM output")


def _diagnostic_to_dict(*, d: OpenSpecDiagnostic) -> dict[str, str]:
    return {
        "severity": d.severity.value,
        "message": d.message,
        "path": d.path,
        "code": d.code,
    }


__all__ = [
    "DEFAULT_VALIDATE_TIMEOUT",
    "MetaSpecifier",
    "render_proposal",
    "template_proposal",
]
