"""
TDD Tests for Experimental API Markers.

Tests verify that @experimental decorator:
1. Emits DeprecationWarning on instantiation
2. Updates docstring to indicate experimental status
3. Works with classes and functions
4. Does not break core functionality
"""

import warnings

from cemaf.context.context import Context
from cemaf.core.experimental import experimental
from cemaf.core.mind_state import MindState


def test_experimental_decorator_warns_on_class_instantiation():
    """
    GIVEN: A class marked with @experimental
    WHEN: The class is instantiated
    THEN: Should emit DeprecationWarning with stability message
    """

    @experimental
    class TestClass:
        """Test class."""

        def __init__(self) -> None:
            self.value = 42

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        instance = TestClass()

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "experimental" in str(w[0].message).lower()
        assert "subject to change" in str(w[0].message).lower()
        assert instance.value == 42


def test_experimental_decorator_updates_docstring():
    """
    GIVEN: A class marked with @experimental
    WHEN: The class is defined
    THEN: Docstring should be prefixed with experimental warning
    """

    @experimental
    class TestClass:
        """Original docstring."""

        pass

    assert "EXPERIMENTAL" in TestClass.__doc__
    assert "Original docstring" in TestClass.__doc__


def test_experimental_decorator_preserves_functionality():
    """
    GIVEN: A class marked with @experimental
    WHEN: Methods are called on the instance
    THEN: All functionality should work normally
    """

    @experimental
    class TestClass:
        """Test class."""

        def add(self, a: int, b: int) -> int:
            return a + b

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        instance = TestClass()

        assert instance.add(2, 3) == 5


def test_experimental_decorator_works_with_functions():
    """
    GIVEN: A function marked with @experimental
    WHEN: The function is called
    THEN: Should emit DeprecationWarning and return correct result
    """

    @experimental
    def experimental_func(x: int) -> int:
        """Experimental function."""
        return x * 2

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = experimental_func(5)

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert result == 10


def test_mind_state_is_marked_experimental():
    """
    GIVEN: MindState class
    WHEN: An instance is created
    THEN: Should emit experimental warning
    """
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        MindState(id="test-id")

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "MindState" in str(w[0].message)


def test_mind_state_docstring_indicates_unstable():
    """
    GIVEN: MindState class
    WHEN: Docstring is checked
    THEN: Should indicate unstable/experimental status
    """
    assert "STABILITY" in MindState.__doc__
    assert "Unstable" in MindState.__doc__
    assert "experimental" in MindState.__doc__.lower()


def test_mind_state_build_works_despite_experimental():
    """
    GIVEN: MindState class marked experimental
    WHEN: build() is called
    THEN: Should work normally (though incomplete)
    """
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")

        mind_state = MindState.build([])
        assert mind_state.id is not None
        assert isinstance(mind_state.context, Context)


def test_mind_state_to_prompt_works_despite_experimental():
    """
    GIVEN: MindState instance marked experimental
    WHEN: to_prompt() is called
    THEN: Should return a string (even if empty/incomplete)
    """
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")

        mind_state = MindState(id="test-id")
        prompt = mind_state.to_prompt()

        assert isinstance(prompt, str)
