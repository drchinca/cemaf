"""Bridge CEMAF Blueprints to MCP prompt format."""

import re

from cemaf.blueprint.core import Blueprint
from cemaf.core.types import JSON
from cemaf.mcp.types import MCPPrompt, MCPPromptArgument


class PromptBridge:
    """Bridge between CEMAF Blueprint and MCP prompt format."""

    @staticmethod
    def to_mcp(blueprint: Blueprint) -> MCPPrompt:
        """Convert CEMAF Blueprint to MCP prompt."""
        arguments: list[MCPPromptArgument] = []

        instruction = blueprint.instruction
        if instruction:
            placeholders = re.findall(r"\{(\w+)\}", instruction)
            for name in set(placeholders):
                arguments.append(
                    MCPPromptArgument(
                        name=name,
                        description=f"Value for {{{name}}}",
                        required=True,
                    )
                )

        return MCPPrompt(
            name=blueprint.id,
            description=blueprint.description or blueprint.name,
            arguments=tuple(arguments),
        )

    @staticmethod
    def get_prompt_text(
        blueprint: Blueprint,
        arguments: JSON,
    ) -> str:
        """Render blueprint as prompt text with arguments."""
        text = blueprint.to_prompt()

        for key, value in arguments.items():
            placeholder = "{" + key + "}"
            text = text.replace(placeholder, str(value))

        return text
