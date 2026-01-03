"""Bridge CEMAF Blueprints to MCP prompt format."""

from __future__ import annotations

from cemaf.mcp.types import MCPPrompt, MCPPromptArgument


class PromptBridge:
    """
    Bridge between CEMAF Blueprint and MCP prompt format.
    """

    @staticmethod
    def to_mcp(blueprint: Blueprint) -> MCPPrompt:  # noqa: F821
        """
        Convert CEMAF Blueprint to MCP prompt.

        Blueprint fields become prompt arguments.
        """
        # Extract arguments from blueprint structure
        arguments = []

        # The instruction is a key input
        if blueprint.instruction:
            arguments.append(
                MCPPromptArgument(
                    name="instruction",
                    description="Override the default instruction",
                    required=False,
                )
            )

        # Participants can be customized
        if blueprint.participants:
            arguments.append(
                MCPPromptArgument(
                    name="participants",
                    description="Custom participant definitions",
                    required=False,
                )
            )

        # Context is always available
        arguments.append(
            MCPPromptArgument(
                name="context",
                description="Additional context for the prompt",
                required=False,
            )
        )

        return MCPPrompt(
            name=blueprint.id,
            description=blueprint.description or f"Blueprint: {blueprint.name}",
            arguments=tuple(arguments),
        )

    @staticmethod
    def get_prompt_text(blueprint: Blueprint, arguments: dict | None = None) -> str:  # noqa: F821
        """
        Generate prompt text from blueprint with optional argument overrides.

        Args:
            blueprint: The Blueprint to convert
            arguments: Optional argument overrides

        Returns:
            Formatted prompt string
        """
        args = arguments or {}

        # Start with the base prompt
        prompt = blueprint.to_prompt()

        # Apply any context override
        if "context" in args:
            prompt = f"{prompt}\n\n## Additional Context\n{args['context']}"

        # Apply instruction override
        if "instruction" in args:
            # Replace instruction section
            prompt = prompt.replace(
                f"## Instructions\n{blueprint.instruction}",
                f"## Instructions\n{args['instruction']}",
            )

        return prompt
