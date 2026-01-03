"""
Base Registry - Generic registry pattern for protocol-based components.

Provides common registry functionality that can be specialized for tools,
skills, or any other protocol-based components in CEMAF.

This module eliminates code duplication between ToolRegistry and SkillRegistry
by providing a generic base class with all common functionality.

Usage:
    class ToolRegistry(BaseRegistry[Tool]):
        def __init__(self, **kwargs):
            super().__init__(
                item_type_name="Tool",
                id_attribute="id",
                **kwargs
            )

        def _implements_protocol(self, obj: Any) -> bool:
            # Tool-specific protocol checking
            return isinstance(obj, Tool)
"""

import importlib
import inspect
import pkgutil
from typing import Any


class RegistryError(Exception):
    """Raised when registry operations fail."""

    pass


class BaseRegistry[T]:
    """
    Generic registry for protocol-based components.

    This base class provides all common registry functionality:
    - Registration (classes and instances)
    - Dependency injection
    - Auto-discovery from packages
    - Namespace support
    - CRUD operations

    Type Parameters:
        T: The type of items this registry manages (Tool, Skill, etc.)

    Subclasses must:
        1. Call super().__init__ with item_type_name
        2. Implement _implements_protocol() for protocol validation
        3. Optionally override _get_item_id() if ID extraction differs

    Example:
        >>> class ToolRegistry(BaseRegistry[Tool]):
        ...     def __init__(self, **kwargs):
        ...         super().__init__(item_type_name="Tool", **kwargs)
        ...
        ...     def _implements_protocol(self, obj: Any) -> bool:
        ...         if inspect.isclass(obj):
        ...             return all(hasattr(obj, attr) for attr in ['id', 'schema', 'execute'])
        ...         return isinstance(obj, Tool)
    """

    def __init__(
        self,
        *,
        item_type_name: str,
        id_attribute: str = "id",
        dependencies: dict[str, Any] | None = None,
        namespace: str = "",
    ) -> None:
        """
        Initialize base registry.

        Args:
            item_type_name: Human-readable name for error messages ("Tool", "Skill", etc.)
            id_attribute: Attribute name to get item ID (default: "id")
            dependencies: Dependencies to inject into constructors
            namespace: Optional namespace prefix for item IDs
        """
        self._items: dict[str, T] = {}
        self._item_type_name = item_type_name
        self._id_attribute = id_attribute
        self._dependencies = dependencies or {}
        self._namespace = namespace

    def register(self, item_class: type[T]) -> None:
        """
        Register an item class with automatic dependency injection.

        The class will be instantiated using available dependencies.
        Constructor parameters matching dependency keys will be injected.

        Args:
            item_class: Class to register (will be instantiated)

        Raises:
            RegistryError: If class doesn't implement required protocol
            RegistryError: If required dependencies are missing
            RegistryError: If item ID already registered
        """
        # Validate that class implements protocol
        if not self._implements_protocol(item_class):
            raise RegistryError(
                f"{self._item_type_name} class {item_class.__name__} does not implement "
                f"{self._item_type_name} protocol. Check required attributes and methods."
            )

        # Instantiate with dependency injection
        try:
            item_instance = self._instantiate_with_dependencies(item_class)
        except Exception as e:
            # Get item ID for error message (use class name as fallback)
            item_id = self._get_error_id(item_class)

            raise RegistryError(
                f"Failed to instantiate {self._item_type_name.lower()} '{item_id}': "
                f"Missing required dependency or constructor error: {e}"
            ) from e

        # Register the instance
        self.register_instance(item_instance)

    def register_instance(self, item: T) -> None:
        """
        Register an already-instantiated item.

        Args:
            item: Item instance to register

        Raises:
            RegistryError: If item doesn't implement required protocol
            RegistryError: If item ID already registered
        """
        # Validate protocol implementation
        if not self._implements_protocol(item):
            raise RegistryError(
                f"{self._item_type_name} {item.__class__.__name__} does not implement "
                f"{self._item_type_name} protocol"
            )

        # Get storage key (with namespace prefix if set)
        item_id = str(self._get_item_id(item))
        storage_key = self._add_namespace_prefix(item_id)

        # Check for duplicates
        if storage_key in self._items:
            raise RegistryError(f"{self._item_type_name} already registered: {storage_key}")

        # Store item
        self._items[storage_key] = item

    def get(self, item_id: str) -> T | None:
        """
        Get an item by ID.

        Args:
            item_id: Item identifier (use full namespaced ID if namespace is set)

        Returns:
            Item instance or None if not found
        """
        return self._items.get(item_id)

    def get_or_raise(self, item_id: str) -> T:
        """
        Get an item by ID, raising error if not found.

        Args:
            item_id: Item identifier

        Returns:
            Item instance

        Raises:
            RegistryError: If item not found
        """
        item = self.get(item_id)
        if item is None:
            raise RegistryError(f"{self._item_type_name} not found: {item_id}")
        return item

    def has(self, item_id: str) -> bool:
        """
        Check if item is registered.

        Args:
            item_id: Item identifier (use full namespaced ID if namespace is set)

        Returns:
            True if item exists
        """
        return item_id in self._items

    def list_items(self) -> list[T]:
        """
        List all registered items.

        Returns:
            List of all item instances
        """
        return list(self._items.values())

    def count(self) -> int:
        """
        Count registered items.

        Returns:
            Number of items in registry
        """
        return len(self._items)

    def clear(self) -> None:
        """
        Remove all items from registry.

        Useful for testing or dynamic item management.
        """
        self._items.clear()

    @classmethod
    def auto_discover(
        cls,
        module_path: str,
        *,
        dependencies: dict[str, Any] | None = None,
        namespace: str = "",
    ) -> BaseRegistry[T]:
        """
        Auto-discover and register items from a Python package.

        Scans the given module path for classes implementing the required protocol
        and automatically registers them with dependency injection.

        Args:
            module_path: Python module path to scan (e.g., "myapp.tools")
            dependencies: Dependencies to inject into discovered items
            namespace: Optional namespace for discovered items

        Returns:
            Registry with all discovered items registered

        Raises:
            RegistryError: If module cannot be imported or discovery fails

        Example:
            >>> registry = ToolRegistry.auto_discover(
            ...     "myapp.tools",
            ...     dependencies={"client": client}
            ... )
        """
        registry = cls(dependencies=dependencies, namespace=namespace)

        try:
            # Import the module
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise RegistryError(
                f"Failed to discover {registry._item_type_name.lower()}s from '{module_path}': "
                f"Module not found or import error: {e}"
            ) from e

        # Scan for classes
        discovered_count = 0

        # Check if it's a package (has __path__)
        if hasattr(module, "__path__"):
            # It's a package, scan all submodules
            for _importer, modname, _ispkg in pkgutil.walk_packages(
                path=module.__path__,
                prefix=module.__name__ + ".",
            ):
                try:
                    submodule = importlib.import_module(modname)
                    discovered_count += registry._discover_from_module(submodule)
                except Exception:
                    # Skip modules that can't be imported
                    continue
        else:
            # It's a single module
            discovered_count = registry._discover_from_module(module)

        if discovered_count == 0:
            raise RegistryError(
                f"Failed to discover {registry._item_type_name.lower()}s from '{module_path}': "
                f"No {registry._item_type_name} implementations found"
            )

        return registry

    def _discover_from_module(self, module: Any) -> int:
        """
        Discover items from a single module.

        Args:
            module: Python module to scan

        Returns:
            Number of items discovered
        """
        discovered = 0

        for _name, obj in inspect.getmembers(module, inspect.isclass):
            # Skip imported classes (only register classes defined in this module)
            if obj.__module__ != module.__name__:
                continue

            # Check if it implements required protocol
            if self._implements_protocol(obj):
                try:
                    self.register(obj)
                    discovered += 1
                except RegistryError:
                    # Item already registered or other error, skip
                    continue

        return discovered

    def _instantiate_with_dependencies(self, item_class: type[T]) -> T:
        """
        Instantiate class with dependency injection.

        Inspects constructor signature and injects matching dependencies.

        Args:
            item_class: Class to instantiate

        Returns:
            Instantiated item

        Raises:
            Exception: If instantiation fails (missing deps, etc.)
        """
        # Get constructor signature
        sig = inspect.signature(item_class.__init__)

        # Build kwargs from available dependencies
        kwargs: dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            # Skip self, *args, **kwargs
            if param_name == "self":
                continue
            if param.kind == inspect.Parameter.VAR_POSITIONAL:  # *args
                continue
            if param.kind == inspect.Parameter.VAR_KEYWORD:  # **kwargs
                continue

            # Check if we have this dependency
            if param_name in self._dependencies:
                kwargs[param_name] = self._dependencies[param_name]
            elif param.default is inspect.Parameter.empty:
                # Required parameter with no default, and we don't have it
                raise ValueError(f"Missing required dependency: {param_name}")

        # Instantiate with injected dependencies
        return item_class(**kwargs)  # type: ignore

    def _add_namespace_prefix(self, item_id: str) -> str:
        """
        Add namespace prefix to item ID for storage.

        Args:
            item_id: Original item ID

        Returns:
            Item ID with namespace prefix (if namespace is set)
        """
        if self._namespace:
            return f"{self._namespace}.{item_id}"
        return item_id

    def _get_item_id(self, item: T) -> Any:
        """
        Extract ID from item instance.

        Can be overridden by subclasses if ID extraction differs.

        Args:
            item: Item instance

        Returns:
            Item ID (typically a string or ID type)
        """
        return getattr(item, self._id_attribute)

    def _get_error_id(self, item_class: type[T]) -> str:
        """
        Get item ID for error messages.

        Falls back to class name if ID cannot be extracted.

        Args:
            item_class: Item class

        Returns:
            ID string for error messages
        """
        # Try instantiating with no args to get ID
        try:
            temp = item_class()  # type: ignore
            return str(getattr(temp, self._id_attribute))
        except Exception:
            pass

        # Fall back to class name
        return item_class.__name__

    def _implements_protocol(self, obj: Any) -> bool:
        """
        Check if object implements the required protocol.

        MUST be implemented by subclasses.

        Args:
            obj: Object to check (class or instance)

        Returns:
            True if object implements required protocol
        """
        raise NotImplementedError(
            f"Subclass must implement _implements_protocol() to validate {self._item_type_name} protocol"
        )

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        namespace_info = f" namespace={self._namespace}" if self._namespace else ""
        return f"{self.__class__.__name__}(items={self.count()}{namespace_info})"
