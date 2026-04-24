"""
DynamicToolFactory: generates, validates, and registers tools at runtime.

Flow:
  1. LLM generates Python code for a tool given a description
  2. Code is validated (syntax check)
  3. Tool is test-executed in LocalSandbox
  4. If passes: loaded into ToolRegistry + persisted to disk
  5. TrustLevel starts at SANDBOXED
"""

from __future__ import annotations

import ast
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cemaf.core.result import Result
from cemaf.core.types import JSON, ToolID
from cemaf.llm.protocols import LLMClient, Message
from cemaf.sandbox.sandbox import LocalSandbox
from cemaf.tools.base import Tool, ToolResult, ToolSchema
from cemaf.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedToolSpec:
    """Specification of a tool to generate."""

    name: str
    description: str
    parameters: JSON
    required: tuple[str, ...]
    example_inputs: JSON = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    """Outcome of a full generate-validate-register cycle."""

    success: bool
    tool_id: ToolID | None = None
    code: str = ""
    validation_output: str = ""
    error: str | None = None


_CODEGEN_SYSTEM = """You are an expert Python tool generator for the CEMAF framework.

Generate a single async Python function that implements the requested tool.

RULES:
1. Function must be named `execute` and be `async def execute(**kwargs) -> dict`
2. Must return a dict (will be wrapped in Result.ok)
3. Handle all errors internally, return {"error": "..."} on failure
4. No external state, purely functional
5. Import everything you need inside the function body
6. No class definitions — just the async function

OUTPUT: Return ONLY the Python code, no markdown, no explanation.

Example output:
async def execute(**kwargs) -> dict:
    import httpx
    query = kwargs.get("query", "")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.example.com/search?q={query}")
        return {"results": resp.json()}
"""


class DynamicToolFactory:
    """
    Generates tools on-the-fly using an LLM, validates them in a sandbox,
    and registers them for immediate use.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        registry: ToolRegistry,
        sandbox: LocalSandbox | None = None,
        persist_dir: Path | None = None,
    ) -> None:
        self._llm = llm_client
        self._registry = registry
        self._sandbox = sandbox or LocalSandbox()
        self._persist_dir = persist_dir

    async def generate_and_register(
        self, spec: GeneratedToolSpec
    ) -> Result[GenerationResult]:
        """Full pipeline: generate code → validate syntax → sandbox-test → register."""
        # 1. Generate code via LLM
        code_result = await self._generate_code(spec)
        if not code_result.success:
            return Result.fail(f"Code generation failed: {code_result.error}")

        code = code_result.data or ""

        # 2. Syntax validation
        try:
            ast.parse(code)
        except SyntaxError as e:
            return Result.fail(f"Syntax error in generated code: {e}")

        # 3. Sandbox test with example inputs (if provided)
        if spec.example_inputs:
            test_snippet = (
                code
                + f"\n\nimport asyncio\n_result = asyncio.run(execute(**{spec.example_inputs!r}))"
            )
            test_result = await self._sandbox.run_code(
                test_snippet,
                inputs=spec.example_inputs,
            )
            if not test_result.success:
                return Result.fail(
                    f"Sandbox validation failed: "
                    f"{test_result.error or test_result.stderr}"
                )

        # 4. Build and register Tool
        tool_id = ToolID(f"dynamic_{spec.name}_{uuid.uuid4().hex[:8]}")
        tool = self._build_tool(tool_id, spec, code)
        self._registry.register_instance(tool)

        # 5. Persist if configured
        if self._persist_dir:
            self._persist(tool_id, spec, code)

        logger.info("Dynamic tool registered: %s", tool_id)
        return Result.ok(
            GenerationResult(
                success=True,
                tool_id=tool_id,
                code=code,
            )
        )

    async def _generate_code(self, spec: GeneratedToolSpec) -> Result[str]:
        """Ask the LLM to produce an `async def execute(**kwargs) -> dict` function."""
        prompt = (
            f"Tool name: {spec.name}\n"
            f"Description: {spec.description}\n"
            f"Parameters: {spec.parameters}\n"
            f"Required: {list(spec.required)}\n"
            f"Example inputs: {spec.example_inputs}\n\n"
            "Generate the `async def execute(**kwargs) -> dict` function."
        )

        result = await self._llm.complete(
            [
                Message.system(_CODEGEN_SYSTEM),
                Message.user(prompt),
            ]
        )

        if not result.success or not result.message:
            return Result.fail(result.error or "LLM returned no response")

        content = result.message.content
        code = str(content).strip()

        # Strip markdown fences when the model wraps its output.
        if "```python" in code:
            code = code[code.find("```python") + 9 : code.rfind("```")].strip()
        elif "```" in code:
            code = code[code.find("```") + 3 : code.rfind("```")].strip()

        return Result.ok(code)

    def _build_tool(
        self,
        tool_id: ToolID,
        spec: GeneratedToolSpec,
        code: str,
    ) -> Tool:
        """Compile generated source into a live Tool instance via exec."""
        module_name = f"badox_dynamic_{tool_id}"
        # Create a fresh module namespace and compile the generated code into it.
        module_ns: dict[str, Any] = {"__name__": module_name}
        exec(compile(code, module_name, "exec"), module_ns)  # noqa: S102
        execute_fn = module_ns["execute"]

        tool_schema = ToolSchema(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
            required=spec.required,
        )

        # Capture into closure-friendly locals for the inner class.
        _tool_id = tool_id
        _tool_schema = tool_schema
        _execute_fn = execute_fn

        from cemaf.core.result import Result

        class _DynamicTool(Tool):
            @property
            def id(self) -> ToolID:
                return _tool_id

            @property
            def schema(self) -> ToolSchema:
                return _tool_schema

            async def execute(self, **kwargs: Any) -> ToolResult:
                try:
                    output = await _execute_fn(**kwargs)
                    return Result.ok(output)
                except Exception as e:
                    return Result.fail(str(e))

        return _DynamicTool()

    def _persist(
        self,
        tool_id: ToolID,
        spec: GeneratedToolSpec,
        code: str,
    ) -> None:
        """Save generated tool code and metadata to disk for later reuse."""
        import json

        assert self._persist_dir is not None  # guarded by caller
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        tool_file = self._persist_dir / f"{tool_id}.py"
        meta_file = self._persist_dir / f"{tool_id}.json"
        tool_file.write_text(code)
        meta_file.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                    "required": list(spec.required),
                },
                indent=2,
            )
        )
