"""
Type-safe context paths - Provides typed access to context with IDE support.

Eliminates string-based path fragility with compile-time type checking
and IDE autocomplete.

Usage:
    # Define typed paths
    class Paths:
        user_name = ContextPath[str]("user.name")
        search_results = ContextPath[list]("tools.search.results")
        confidence = ContextPath[float]("analysis.confidence")

    # Use with TypedContext wrapper
    ctx = TypedContext(Context())
    ctx = ctx.set(Paths.user_name, "Alice")  # Type-safe
    name = ctx.get(Paths.user_name)  # Returns str, IDE knows the type!

    # Still backward compatible with string paths
    ctx._ctx.set("user.name", "Alice")  # Works but not type-safe
"""

from typing import Any, TypeVar, overload

from cemaf.context.context import Context

T = TypeVar("T")


class ContextPath[T]:
    """
    Type-safe path to a context value.

    Provides compile-time type checking and IDE autocomplete support
    while maintaining backward compatibility with string paths.

    Type Parameters:
        T: The type of value stored at this path

    Args:
        path: Dot-notation path string (e.g., "user.profile.name")
        description: Optional description for documentation

    Example:
        user_id = ContextPath[str]("user.id")
        scores = ContextPath[list[float]]("analysis.scores")
    """

    def __init__(self, path: str, *, description: str = "") -> None:
        """
        Initialize a typed context path.

        Args:
            path: Dot-notation path string
            description: Optional description for documentation
        """
        self._path = path
        self._description = description

    @property
    def path(self) -> str:
        """Get the underlying string path."""
        return self._path

    @property
    def description(self) -> str:
        """Get the path description."""
        return self._description

    def __str__(self) -> str:
        """String representation."""
        return self._path

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        if self._description:
            return f"ContextPath[{self._path}]({self._description})"
        return f"ContextPath[{self._path}]"

    def __hash__(self) -> int:
        """Make paths hashable for use in sets/dicts."""
        return hash(self._path)

    def __eq__(self, other: object) -> bool:
        """Compare paths by their path string."""
        if isinstance(other, ContextPath):
            return self._path == other._path
        return False


class TypedContext:
    """
    Wrapper around Context providing type-safe path access.

    Maintains backward compatibility while adding type safety for
    typed paths. You can mix typed paths and string paths.

    Usage:
        ctx = TypedContext(Context())
        ctx = ctx.set(Paths.user_name, "Alice")
        name = ctx.get(Paths.user_name)  # Type is inferred as str

        # Access underlying Context
        raw_ctx = ctx.unwrap()
    """

    def __init__(self, context: Context) -> None:
        """
        Initialize typed context wrapper.

        Args:
            context: Underlying Context instance
        """
        self._ctx = context

    @overload
    def get(self, path: ContextPath[T]) -> T | None: ...

    @overload
    def get(self, path: ContextPath[T], default: T) -> T: ...

    @overload
    def get(self, path: str) -> Any: ...

    @overload
    def get(self, path: str, default: Any) -> Any: ...

    def get(self, path: ContextPath[T] | str, default: Any = None) -> T | Any:
        """
        Get value from context with type safety.

        Args:
            path: Typed ContextPath or string path
            default: Default value if path doesn't exist

        Returns:
            Value at path with inferred type, or default
        """
        if isinstance(path, ContextPath):
            return self._ctx.get(path.path, default)
        return self._ctx.get(path, default)

    @overload
    def set(self, path: ContextPath[T], value: T) -> TypedContext: ...

    @overload
    def set(self, path: str, value: Any) -> TypedContext: ...

    def set(self, path: ContextPath[T] | str, value: T | Any) -> TypedContext:
        """
        Set value in context with type safety.

        Args:
            path: Typed ContextPath or string path
            value: Value to set (type-checked if using ContextPath)

        Returns:
            New TypedContext with updated value
        """
        if isinstance(path, ContextPath):
            new_ctx = self._ctx.set(path.path, value)
        else:
            new_ctx = self._ctx.set(path, value)
        return TypedContext(new_ctx)

    def delete(self, path: ContextPath[Any] | str) -> TypedContext:
        """
        Delete value from context.

        Args:
            path: Typed ContextPath or string path

        Returns:
            New TypedContext with path removed
        """
        if isinstance(path, ContextPath):
            new_ctx = self._ctx.delete(path.path)
        else:
            new_ctx = self._ctx.delete(path)
        return TypedContext(new_ctx)

    def merge(self, other: TypedContext | Context) -> TypedContext:
        """
        Merge another context into this one.

        Args:
            other: TypedContext or Context to merge

        Returns:
            New TypedContext with merged data
        """
        if isinstance(other, TypedContext):
            new_ctx = self._ctx.merge(other._ctx)
        else:
            new_ctx = self._ctx.merge(other)
        return TypedContext(new_ctx)

    def unwrap(self) -> Context:
        """
        Get the underlying Context instance.

        Returns:
            Raw Context object
        """
        return self._ctx

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary.

        Returns:
            Dictionary representation of context data
        """
        return self._ctx.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TypedContext:
        """
        Create TypedContext from dictionary.

        Args:
            data: Dictionary data

        Returns:
            New TypedContext instance
        """
        return cls(Context.from_dict(data))

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"TypedContext({self._ctx.data})"


def create_path_builder(prefix: str = "") -> type:
    """
    Create a dynamic path builder class.

    Enables fluent path construction with autocomplete support.

    Args:
        prefix: Optional prefix for all paths

    Returns:
        Path builder class

    Example:
        UserPaths = create_path_builder("user")
        user = UserPaths()
        name_path = user.name  # Creates ContextPath[Any]("user.name")
    """

    class PathBuilder:
        """Dynamic path builder."""

        def __init__(self) -> None:
            self._prefix = prefix

        def __getattr__(self, name: str) -> ContextPath[Any]:
            """Create path on attribute access."""
            if name.startswith("_"):
                raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

            full_path = f"{self._prefix}.{name}" if self._prefix else name
            return ContextPath[Any](full_path)

    return PathBuilder
