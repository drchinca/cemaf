"""
Context module - Context engineering for LLM agents.

Context engineering involves:
- COMPILATION: Assembling relevant context for a task
- BUDGETING: Managing token limits
- SLICING: Breaking context into manageable chunks
- VERSIONING: Tracking context versions/hashes
- PATCHING: Tracking provenance of context changes
"""

from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    GreedySelectionAlgorithm,
    KnapsackSelectionAlgorithm,
    OptimalSelectionAlgorithm,
    SelectionResult,
)
from cemaf.context.budget import BudgetAllocation, TokenBudget
from cemaf.context.compiler import CompiledContext, ContextCompiler
from cemaf.context.context import Context
from cemaf.context.patch import (
    ContextPatch,
    PatchLog,
    PatchOperation,
    PatchSource,
)

__all__ = [
    "ContextCompiler",
    "CompiledContext",
    "TokenBudget",
    "BudgetAllocation",
    "Context",
    "AdvancedContextCompiler",
    # Selection algorithms
    "ContextSelectionAlgorithm",
    "GreedySelectionAlgorithm",
    "KnapsackSelectionAlgorithm",
    "OptimalSelectionAlgorithm",
    "SelectionResult",
    # Patch system
    "ContextPatch",
    "PatchOperation",
    "PatchSource",
    "PatchLog",
]
