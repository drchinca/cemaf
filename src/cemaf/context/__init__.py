"""
Context module - Context engineering for LLM agents.

Context engineering involves:
- COMPILATION: Assembling relevant context for a task
- BUDGETING: Managing token limits
- SLICING: Breaking context into manageable chunks
- VERSIONING: Tracking context versions/hashes
- PATCHING: Tracking provenance of context changes
- TYPE-SAFE PATHS: Typed context access with IDE autocomplete
- SOURCE MANAGEMENT: Rich metadata for context sources
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
from cemaf.context.merge import (
    DEFAULT_MERGE_STRATEGY,
    DeepMergeStrategy,
    LastWriteWinsStrategy,
    MergeConflict,
    MergeConflictError,
    MergeResult,
    MergeStrategy,
    RaiseOnConflictStrategy,
    ReducerMergeStrategy,
    create_merge_strategy,
)
from cemaf.context.patch import (
    ContextPatch,
    PatchLog,
    PatchOperation,
    PatchSource,
)
from cemaf.context.paths import ContextPath, TypedContext, create_path_builder
from cemaf.context.source import ContextSource

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
    # Merge strategies (new - parallel context merge)
    "MergeStrategy",
    "MergeResult",
    "MergeConflict",
    "MergeConflictError",
    "LastWriteWinsStrategy",
    "RaiseOnConflictStrategy",
    "DeepMergeStrategy",
    "ReducerMergeStrategy",
    "DEFAULT_MERGE_STRATEGY",
    "create_merge_strategy",
    # Type-safe paths (new in Phase 1)
    "ContextPath",
    "TypedContext",
    "create_path_builder",
    # Source management (new in Phase 1)
    "ContextSource",
]
