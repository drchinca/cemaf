"""
Context module - Context engineering for LLM agents.

Context engineering involves:
- COMPILATION: Assembling relevant context for a task
- BUDGETING: Managing token limits
- SLICING: Breaking context into manageable chunks
- VERSIONING: Tracking context versions/hashes
- PATCHING: Tracking provenance of context changes
"""

from cemaf.context.compiler import ContextCompiler, CompiledContext
from cemaf.context.budget import TokenBudget, BudgetAllocation
from cemaf.context.context import Context
from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.patch import (
    ContextPatch,
    PatchOperation,
    PatchSource,
    PatchLog,
)

__all__ = [
    "ContextCompiler",
    "CompiledContext",
    "TokenBudget",
    "BudgetAllocation",
    "Context",
    "AdvancedContextCompiler",
    # Patch system
    "ContextPatch",
    "PatchOperation",
    "PatchSource",
    "PatchLog",
]

