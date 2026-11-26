"""Knowledge ontologies (SPEC-27): classes, properties and relations a knowledge graph should follow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TypeIs

from cemaf.knowledge.models import KGEntity


class OntologyDefinitionError(ValueError):
    """The ontology itself is malformed."""


class PropertyType(StrEnum):
    """The value types an ontology property can declare."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    LIST = "list"
    OBJECT = "object"


class ViolationKind(StrEnum):
    """Which ontology rule a write broke."""

    UNKNOWN_CLASS = "unknown_class"
    MISSING_PROPERTY = "missing_property"
    UNKNOWN_PROPERTY = "unknown_property"
    WRONG_PROPERTY_TYPE = "wrong_property_type"
    VALUE_NOT_ALLOWED = "value_not_allowed"
    UNKNOWN_RELATION = "unknown_relation"
    WRONG_SOURCE_CLASS = "wrong_source_class"
    WRONG_TARGET_CLASS = "wrong_target_class"
    MISSING_ENDPOINT = "missing_endpoint"
    TOO_MANY_RELATIONS = "too_many_relations"


@dataclass(frozen=True, slots=True)
class PropertySpec:
    """One property a class declares."""

    name: str
    type: PropertyType
    required: bool = False
    allowed: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class OntologyClass:
    """A class of entities; an entity's type names its class."""

    name: str
    is_a: str | None = None
    properties: tuple[PropertySpec, ...] = ()
    closed: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class RelationSpec:
    """A relation type, the classes it may join, and how many a source may have."""

    name: str
    source: str
    target: str
    max_per_source: int | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class OntologyViolation:
    """One broken ontology rule, recorded instead of rejecting the write."""

    kind: ViolationKind
    subject_id: str
    message: str


def _matches_type(*, value: object, expected: PropertyType) -> bool:
    """Whether a property value fits its declared type."""
    match expected:
        case PropertyType.STRING:
            return isinstance(value, str)
        case PropertyType.INTEGER:
            return _is_integer(value)
        case PropertyType.NUMBER:
            return isinstance(value, int | float) and not isinstance(value, bool)
        case PropertyType.BOOLEAN:
            return isinstance(value, bool)
        case PropertyType.DATE:
            if isinstance(value, date) and not isinstance(value, datetime):
                return True
            return isinstance(value, str) and _parses(parse=date.fromisoformat, text=value)
        case PropertyType.DATETIME:
            if isinstance(value, datetime):
                return True
            return isinstance(value, str) and _parses(parse=datetime.fromisoformat, text=value)
        case PropertyType.LIST:
            return isinstance(value, list | tuple)
        case PropertyType.OBJECT:
            return isinstance(value, Mapping)


def _one(*, kind: ViolationKind, subject_id: str, message: str) -> tuple[OntologyViolation, ...]:
    return (OntologyViolation(kind=kind, subject_id=subject_id, message=message),)


def _is_integer(value: object, /) -> TypeIs[int]:
    """An int that is not a bool; positional so the type checker can narrow it."""
    return isinstance(value, int) and not isinstance(value, bool)


def _parses(*, parse: Callable[[str], object], text: str) -> bool:
    try:
        parse(text)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class Ontology:
    """A named, versioned set of classes and relations; immutable and hashable."""

    name: str
    version: int
    classes: tuple[OntologyClass, ...]
    relations: tuple[RelationSpec, ...] = ()

    def __post_init__(self) -> None:
        _check_definition(ontology=self)

    def class_named(self, *, name: str) -> OntologyClass | None:
        """The class with this name, or None."""
        return next((cls for cls in self.classes if cls.name == name), None)

    def relation_named(self, *, name: str) -> RelationSpec | None:
        """The relation with this name, or None."""
        return next((rel for rel in self.relations if rel.name == name), None)

    def ancestors(self, *, class_name: str) -> tuple[str, ...]:
        """The class's ancestors, nearest first."""
        chain: list[str] = []
        current = self.class_named(name=class_name)
        while current is not None and current.is_a is not None:
            chain.append(current.is_a)
            current = self.class_named(name=current.is_a)
        return tuple(chain)

    def is_a(self, *, class_name: str, ancestor: str) -> bool:
        """Whether class_name is ancestor or descends from it."""
        if self.class_named(name=class_name) is None:
            return False
        return class_name == ancestor or ancestor in self.ancestors(class_name=class_name)

    def descendants(self, *, class_name: str) -> tuple[str, ...]:
        """Every class that descends from class_name, not including it."""
        return tuple(
            cls.name
            for cls in self.classes
            if cls.name != class_name and class_name in self.ancestors(class_name=cls.name)
        )

    def properties_of(self, *, class_name: str) -> tuple[PropertySpec, ...]:
        """Inherited properties first (root down), then the class's own."""
        lineage = (*reversed(self.ancestors(class_name=class_name)), class_name)
        by_name: dict[str, PropertySpec] = {}
        for name in lineage:
            cls = self.class_named(name=name)
            if cls is not None:
                by_name.update({prop.name: prop for prop in cls.properties})
        return tuple(by_name.values())

    def validate_entity(self, *, entity: KGEntity) -> tuple[OntologyViolation, ...]:
        """Every rule the entity breaks; empty when it conforms."""
        cls = self.class_named(name=entity.type)
        if cls is None:
            message = f"{entity.type!r} is not a class in ontology {self.name!r}"
            return _one(kind=ViolationKind.UNKNOWN_CLASS, subject_id=entity.id, message=message)
        declared = self.properties_of(class_name=cls.name)
        violations = [
            violation
            for prop in declared
            for violation in _check_property(prop=prop, entity=entity, class_name=cls.name)
        ]
        if cls.closed:
            declared_names = {prop.name for prop in declared}
            violations.extend(
                OntologyViolation(
                    kind=ViolationKind.UNKNOWN_PROPERTY,
                    subject_id=entity.id,
                    message=f"{cls.name} is closed and does not declare property {key!r}",
                )
                for key in sorted(entity.properties)
                if key not in declared_names
            )
        return tuple(violations)


def _check_property(
    *, prop: PropertySpec, entity: KGEntity, class_name: str
) -> tuple[OntologyViolation, ...]:
    value = entity.properties.get(prop.name)
    if value is None:
        if not prop.required:
            return ()
        message = f"{class_name} requires property {prop.name!r}"
        return _one(kind=ViolationKind.MISSING_PROPERTY, subject_id=entity.id, message=message)
    if not _matches_type(value=value, expected=prop.type):
        message = f"property {prop.name!r} should be {prop.type}, got {type(value).__name__}"
        return _one(kind=ViolationKind.WRONG_PROPERTY_TYPE, subject_id=entity.id, message=message)
    if prop.allowed and value not in prop.allowed:
        message = f"property {prop.name!r} is {value!r}; allowed: {', '.join(prop.allowed)}"
        return _one(kind=ViolationKind.VALUE_NOT_ALLOWED, subject_id=entity.id, message=message)
    return ()


def _check_definition(*, ontology: Ontology) -> None:
    """Raise OntologyDefinitionError for anything that makes the ontology malformed."""
    _refuse_duplicates(names=[cls.name for cls in ontology.classes], what="class")
    _refuse_duplicates(names=[rel.name for rel in ontology.relations], what="relation")
    class_names = {cls.name for cls in ontology.classes}
    by_name = {cls.name: cls for cls in ontology.classes}
    for cls in ontology.classes:
        if not cls.name:
            raise OntologyDefinitionError("a class needs a non-empty name")
        if cls.is_a is not None and cls.is_a not in class_names:
            raise OntologyDefinitionError(f"class {cls.name!r} is_a unknown class {cls.is_a!r}")
        _refuse_duplicates(names=[prop.name for prop in cls.properties], what=f"property of {cls.name!r}")
        for prop in cls.properties:
            if prop.allowed and prop.type is not PropertyType.STRING:
                raise OntologyDefinitionError(
                    f"property {cls.name}.{prop.name} lists allowed values but is {prop.type}, not string"
                )
    for cls in ontology.classes:
        seen = [cls.name]
        parent = cls.is_a
        while parent is not None:
            if parent in seen:
                raise OntologyDefinitionError(f"inheritance cycle: {' -> '.join([*seen, parent])}")
            seen.append(parent)
            parent = by_name[parent].is_a
        _refuse_retyped_properties(cls=cls, by_name=by_name)
    for rel in ontology.relations:
        for end, class_name in (("from", rel.source), ("to", rel.target)):
            if class_name not in class_names:
                raise OntologyDefinitionError(f"relation {rel.name!r} {end} unknown class {class_name!r}")
        if rel.max_per_source is not None and rel.max_per_source < 1:
            raise OntologyDefinitionError(f"relation {rel.name!r} max_per_source must be at least 1")


def _refuse_retyped_properties(*, cls: OntologyClass, by_name: Mapping[str, OntologyClass]) -> None:
    parent = cls.is_a
    while parent is not None:
        inherited = {prop.name: prop.type for prop in by_name[parent].properties}
        for prop in cls.properties:
            if prop.name in inherited and inherited[prop.name] is not prop.type:
                raise OntologyDefinitionError(
                    f"class {cls.name!r} redeclares inherited property {prop.name!r} "
                    f"as {prop.type}; {parent!r} declares {inherited[prop.name]}"
                )
        parent = by_name[parent].is_a


def _refuse_duplicates(*, names: list[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise OntologyDefinitionError(f"duplicate {what} name {name!r}")
        seen.add(name)
