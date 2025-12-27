"""
Context module - Context engineering for LLM agents.

Context engineering involves:
- COMPILATION: Assembling relevant context for a task
- BUDGETING: Managing token limits
- SLICING: Breaking context into manageable chunks
- VERSIONING: Tracking context versions/hashes
"""

from cemaf.context.compiler import ContextCompiler, CompiledContext
from cemaf.context.budget import TokenBudget, BudgetAllocation
from cemaf.context.context import Context # New import
from cemaf.context.advanced_compiler import AdvancedContextCompiler # New import

__all__ = [
    "ContextCompiler",
    "CompiledContext",
    "TokenBudget",
    "BudgetAllocation",
    "Context", # New entry
    "AdvancedContextCompiler", # New entry
]

