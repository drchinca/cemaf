"""
Experimental API markers for unstable features.

Use the @experimental decorator to mark classes, functions, and methods
that are not yet ready for production use. This communicates to users that:
- The API may change without notice
- Breaking changes may be introduced in minor versions
- Stability is not guaranteed
"""

import functools
import warnings
from typing import Any


def experimental(cls_or_func: Any) -> Any:
    """
    Mark a class or function as experimental (unstable).

    Usage:
        @experimental
        class MyUnstableClass:
            pass

        @experimental
        def my_unstable_function():
            pass

    When imported or used, emits a DeprecationWarning to alert users.
    """
    target_name = getattr(cls_or_func, "__qualname__", str(cls_or_func))

    if isinstance(cls_or_func, type):
        # Class decorator
        original_init = cls_or_func.__init__  # type: ignore[misc]

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            warnings.warn(
                f"{target_name} is experimental and subject to change. "
                "Do not use in production. API stability is not guaranteed.",
                category=DeprecationWarning,
                stacklevel=2,
            )
            original_init(self, *args, **kwargs)

        cls_or_func.__init__ = new_init  # type: ignore[misc]
        # Update docstring to indicate experimental status
        if cls_or_func.__doc__:
            cls_or_func.__doc__ = f"⚠️ EXPERIMENTAL - Subject to change\n\n{cls_or_func.__doc__}"
        return cls_or_func
    else:
        # Function decorator
        @functools.wraps(cls_or_func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                f"{target_name} is experimental and subject to change. "
                "Do not use in production. API stability is not guaranteed.",
                category=DeprecationWarning,
                stacklevel=2,
            )
            return cls_or_func(*args, **kwargs)

        return wrapper
