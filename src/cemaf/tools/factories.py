"""
Factory functions for tool components.

Provides convenient ways to create tool wrappers and utilities
with sensible defaults while maintaining dependency injection principles.

Note:
    Tools are protocol-based abstractions that users implement.
    This module provides factory functions for tool utilities and configurations,
    not for tool instances themselves.

Extension Point:
    This module is designed for extension. Add your custom tool
    implementations and register them here if needed.
"""

# ============================================================================
# EXTEND HERE: Bring Your Own Tool Implementations
# ============================================================================
# This is the extension point for custom tool implementations.
#
# To add your own tool type:
# 1. Implement the Tool protocol (see cemaf.tools.protocols)
# 2. Add a factory function below
# 3. Optionally add a config-based factory
#
# Example (Calculator Tool):
#   from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings

#   from cemaf.core.types import ToolID
#
#   def create_calculator_tool() -> Tool:
#       from your_package import CalculatorTool
#       return CalculatorTool(
#           tool_id=ToolID("calculator"),
#           description="Perform basic arithmetic operations"
#       )
#
# Example (Web Search Tool):
#   def create_web_search_tool(api_key: str | None = None) -> Tool:
#       from your_package import WebSearchTool
#       key = api_key or os.getenv("SEARCH_API_KEY")
#       return WebSearchTool(
#           tool_id=ToolID("web_search"),
#           api_key=key,
#       )
#
#   def create_web_search_tool_from_config( settings: Settings | None = None) -> Tool:
#       api_key = os.getenv("SEARCH_API_KEY")
#       max_results = int(os.getenv("CEMAF_TOOLS_SEARCH_MAX_RESULTS", "10"))
#       return create_web_search_tool(api_key=api_key)
#
# Example (Database Query Tool):
#   def create_database_query_tool(
#       connection_string: str,
#       read_only: bool = True,
#   ) -> Tool:
#       from your_package import DatabaseQueryTool
#       return DatabaseQueryTool(
#           tool_id=ToolID("database_query"),
#           connection_string=connection_string,
#           read_only=read_only,
#       )
#
# Example (File System Tool):
#   def create_filesystem_tool(
#       allowed_paths: tuple[str, ...] = (),
#       read_only: bool = True,
#   ) -> Tool:
#       from your_package import FileSystemTool
#       return FileSystemTool(
#           tool_id=ToolID("filesystem"),
#           allowed_paths=allowed_paths,
#           read_only=read_only,
#       )
#
#   def create_filesystem_tool_from_config( settings: Settings | None = None) -> Tool:
#       allowed_paths_str = os.getenv("CEMAF_TOOLS_FS_ALLOWED_PATHS", "")
#       allowed_paths = tuple(allowed_paths_str.split(",")) if allowed_paths_str else ()
#       read_only = os.getenv("CEMAF_TOOLS_FS_READ_ONLY", "true").lower() == "true"
#       return create_filesystem_tool(allowed_paths, read_only)
#
# Example (HTTP API Tool):
#   def create_http_api_tool(
#       base_url: str,
#       headers: dict[str, str] | None = None,
#   ) -> Tool:
#       from your_package import HTTPAPITool
#       return HTTPAPITool(
#           tool_id=ToolID("http_api"),
#           base_url=base_url,
#           headers=headers or {},
#       )
#
# Example (Code Interpreter Tool):
#   def create_code_interpreter_tool(
#       allowed_languages: tuple[str, ...] = ("python",),
#       timeout_seconds: float = 30.0,
#   ) -> Tool:
#       from your_package import CodeInterpreterTool
#       return CodeInterpreterTool(
#           tool_id=ToolID("code_interpreter"),
#           allowed_languages=allowed_languages,
#           timeout_seconds=timeout_seconds,
#       )
# ============================================================================


# Placeholder for future built-in tool implementations
def create_tool_from_config(tool_type: str, settings: Settings | None = None) -> None:
    """
    Create Tool from environment configuration.

    Args:
        tool_type: Type of tool to create

    Raises:
        ValueError: No built-in tool implementations available

    Note:
        This is a placeholder. Add your own tool implementations
        in the "EXTEND HERE" section above.
    """
    raise ValueError(
        f"No built-in tool implementations for type: {tool_type}. "
        f"To add your own, extend this module in cemaf/tools/factories.py"
    )
