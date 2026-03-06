"""Tests for core BaseRegistry — generic registry pattern."""

import pytest

from cemaf.core.registry import BaseRegistry, RegistryError


class FakeItem:
    """Minimal item for testing."""

    def __init__(self, id: str = "item_1", name: str = "test"):
        self.id = id
        self.name = name


class FakeItemWithDeps:
    """Item requiring constructor dependencies."""

    def __init__(self, id: str = "dep_item", client: object = None):
        self.id = id
        self.client = client


class FakeRegistry(BaseRegistry[FakeItem]):
    """Concrete registry for testing."""

    def __init__(self, **kwargs):
        super().__init__(item_type_name="FakeItem", **kwargs)

    def _implements_protocol(self, obj) -> bool:
        if isinstance(obj, type):
            return hasattr(obj, "id") or "id" in getattr(obj.__init__, "__code__", object()).co_varnames
        return hasattr(obj, "id")


class TestRegistration:
    def test_register_instance(self):
        registry = FakeRegistry()
        item = FakeItem(id="item_1")
        registry.register_instance(item=item)
        assert registry.count() == 1
        assert registry.get(item_id="item_1") is item

    def test_register_instance_duplicate_raises(self):
        registry = FakeRegistry()
        registry.register_instance(item=FakeItem(id="item_1"))
        with pytest.raises(RegistryError, match="already registered"):
            registry.register_instance(item=FakeItem(id="item_1"))

    def test_register_class_with_dependency_injection(self):
        client = object()
        registry = FakeRegistry(dependencies={"client": client})
        registry.register(item_class=FakeItemWithDeps)
        item = registry.get(item_id="dep_item")
        assert item is not None
        assert item.client is client

    def test_register_class_missing_dependency_raises(self):
        class NeedsDep:
            def __init__(self, id: str, required_service: object):
                self.id = id
                self.required_service = required_service

        registry = FakeRegistry()
        with pytest.raises(RegistryError, match="Missing required dependency"):
            registry.register(item_class=NeedsDep)


class TestLookup:
    def test_get_returns_none_for_missing(self):
        registry = FakeRegistry()
        assert registry.get(item_id="nonexistent") is None

    def test_get_or_raise_found(self):
        registry = FakeRegistry()
        item = FakeItem(id="found")
        registry.register_instance(item=item)
        assert registry.get_or_raise(item_id="found") is item

    def test_get_or_raise_missing(self):
        registry = FakeRegistry()
        with pytest.raises(RegistryError, match="not found"):
            registry.get_or_raise(item_id="missing")

    def test_has(self):
        registry = FakeRegistry()
        registry.register_instance(item=FakeItem(id="exists"))
        assert registry.has(item_id="exists") is True
        assert registry.has(item_id="nope") is False


class TestCollectionOps:
    def test_list_items(self):
        registry = FakeRegistry()
        registry.register_instance(item=FakeItem(id="a"))
        registry.register_instance(item=FakeItem(id="b"))
        items = registry.list_items()
        assert len(items) == 2
        ids = {item.id for item in items}
        assert ids == {"a", "b"}

    def test_count(self):
        registry = FakeRegistry()
        assert registry.count() == 0
        registry.register_instance(item=FakeItem(id="x"))
        assert registry.count() == 1

    def test_clear(self):
        registry = FakeRegistry()
        registry.register_instance(item=FakeItem(id="x"))
        registry.register_instance(item=FakeItem(id="y"))
        assert registry.count() == 2
        registry.clear()
        assert registry.count() == 0


class TestNamespace:
    def test_namespace_prefix(self):
        registry = FakeRegistry(namespace="myapp")
        registry.register_instance(item=FakeItem(id="tool_1"))
        assert registry.get(item_id="myapp.tool_1") is not None
        assert registry.get(item_id="tool_1") is None

    def test_no_namespace(self):
        registry = FakeRegistry()
        registry.register_instance(item=FakeItem(id="tool_1"))
        assert registry.get(item_id="tool_1") is not None


class TestProtocolValidation:
    def test_rejects_non_protocol_instance(self):
        class StrictRegistry(BaseRegistry):
            def __init__(self):
                super().__init__(item_type_name="Strict")

            def _implements_protocol(self, obj) -> bool:
                return hasattr(obj, "execute")

        registry = StrictRegistry()
        with pytest.raises(RegistryError, match="does not implement"):
            registry.register_instance(item=FakeItem(id="bad"))

    def test_base_implements_protocol_raises(self):
        """BaseRegistry._implements_protocol must be overridden."""

        class BareRegistry(BaseRegistry):
            def __init__(self):
                super().__init__(item_type_name="Bare")

        registry = BareRegistry()
        with pytest.raises(NotImplementedError):
            registry._implements_protocol(obj=FakeItem())


class TestRepr:
    def test_repr_no_namespace(self):
        registry = FakeRegistry()
        assert "FakeRegistry(items=0)" in repr(registry)

    def test_repr_with_namespace(self):
        registry = FakeRegistry(namespace="ns")
        registry.register_instance(item=FakeItem(id="x"))
        r = repr(registry)
        assert "items=1" in r
        assert "namespace=ns" in r


class TestAutoDiscover:
    def test_auto_discover_invalid_module(self):
        with pytest.raises(RegistryError, match="Module not found"):
            FakeRegistry.auto_discover(module_path="nonexistent.module.xyz")
