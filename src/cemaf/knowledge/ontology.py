"""Knowledge ontologies (SPEC-27): classes, properties and relations a knowledge graph should follow."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, TypeIs

from cemaf.knowledge.models import KGEntity, KGRelation

_log = logging.getLogger(__name__)

YAML_SUFFIXES: Final = frozenset({".yaml", ".yml"})
JSON_SUFFIX: Final = ".json"


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

    def validate_relation(
        self,
        *,
        relation: KGRelation,
        source: KGEntity | None,
        target: KGEntity | None,
        existing_from_source: int,
    ) -> tuple[OntologyViolation, ...]:
        """Every rule the relation breaks; source/target None means not found or not visible."""
        subject_id = f"{relation.source_id}->{relation.target_id}:{relation.type}"
        spec = self.relation_named(name=relation.type)
        if spec is None:
            message = f"{relation.type!r} is not a relation in ontology {self.name!r}"
            return _one(kind=ViolationKind.UNKNOWN_RELATION, subject_id=subject_id, message=message)
        violations = [
            *self._check_endpoint(
                entity=source,
                entity_id=relation.source_id,
                expected=spec.source,
                kind=ViolationKind.WRONG_SOURCE_CLASS,
                end="source",
                subject_id=subject_id,
            ),
            *self._check_endpoint(
                entity=target,
                entity_id=relation.target_id,
                expected=spec.target,
                kind=ViolationKind.WRONG_TARGET_CLASS,
                end="target",
                subject_id=subject_id,
            ),
        ]
        if spec.max_per_source is not None and existing_from_source >= spec.max_per_source:
            violations.append(
                OntologyViolation(
                    kind=ViolationKind.TOO_MANY_RELATIONS,
                    subject_id=subject_id,
                    message=(
                        f"{relation.source_id} already has {existing_from_source} {spec.name!r} relations; "
                        f"at most {spec.max_per_source} allowed"
                    ),
                )
            )
        return tuple(violations)

    def _check_endpoint(
        self,
        *,
        entity: KGEntity | None,
        entity_id: str,
        expected: str,
        kind: ViolationKind,
        end: str,
        subject_id: str,
    ) -> tuple[OntologyViolation, ...]:
        if entity is None:
            message = f"{end} {entity_id} not found or not visible"
            return _one(kind=ViolationKind.MISSING_ENDPOINT, subject_id=subject_id, message=message)
        if self.is_a(class_name=entity.type, ancestor=expected):
            return ()
        message = f"{end} {entity_id} is a {entity.type!r}, not a {expected!r}"
        return (OntologyViolation(kind=kind, subject_id=subject_id, message=message),)


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


_TOP_KEYS: Final = frozenset({"ontology", "version", "classes", "relations"})
_CLASS_KEYS: Final = frozenset({"is_a", "properties", "closed", "description"})
_PROPERTY_KEYS: Final = frozenset({"type", "required", "allowed", "description"})
_RELATION_KEYS: Final = frozenset({"from", "to", "max_per_source", "description"})


def ontology_from_mapping(*, data: Mapping[str, object]) -> Ontology:
    """Build an Ontology from its YAML/JSON structure."""
    _refuse_unknown_keys(data=data, allowed=_TOP_KEYS, where="ontology")
    name = data.get("ontology")
    version = data.get("version")
    if not isinstance(name, str) or not name:
        raise OntologyDefinitionError("'ontology' must be a non-empty name")
    if not _is_integer(version):
        raise OntologyDefinitionError("'version' must be an integer")
    classes = tuple(
        _class_from_mapping(name=class_name, data=body)
        for class_name, body in _section(data=data, key="classes").items()
    )
    relations = tuple(
        _relation_from_mapping(name=rel_name, data=body)
        for rel_name, body in _section(data=data, key="relations").items()
    )
    return Ontology(name=name, version=version, classes=classes, relations=relations)


def load_ontology(*, path: Path) -> Ontology:
    """Load an ontology from a .yaml/.yml or .json file."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OntologyDefinitionError(f"cannot read ontology {path}: {exc}") from exc
    if suffix in YAML_SUFFIXES:
        data = _parse_yaml(text=text, path=path)
    elif suffix == JSON_SUFFIX:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OntologyDefinitionError(f"{path} is not valid JSON: {exc}") from exc
    else:
        raise OntologyDefinitionError(f"{path}: ontologies are .yaml, .yml or .json files")
    if not isinstance(data, Mapping):
        raise OntologyDefinitionError(f"{path} must hold a mapping at the top level")
    ontology = ontology_from_mapping(data=data)
    _log.info(
        "ontology.loaded",
        extra={
            "ontology": ontology.name,
            "version": ontology.version,
            "class_count": len(ontology.classes),
            "relation_count": len(ontology.relations),
        },
    )
    return ontology


def _parse_yaml(*, text: str, path: Path) -> object:
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:
        raise OntologyDefinitionError("YAML ontologies need pyyaml: install cemaf[okf]") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise OntologyDefinitionError(f"{path} is not valid YAML: {exc}") from exc


def _section(*, data: Mapping[str, object], key: str) -> Mapping[str, object]:
    section = data.get(key) or {}
    if not isinstance(section, Mapping):
        raise OntologyDefinitionError(f"'{key}' must be a mapping of names to definitions")
    return section


def _body(*, data: object, where: str) -> Mapping[str, object]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise OntologyDefinitionError(f"{where} must be a mapping")
    return data


def _class_from_mapping(*, name: str, data: object) -> OntologyClass:
    body = _body(data=data, where=f"class {name!r}")
    _refuse_unknown_keys(data=body, allowed=_CLASS_KEYS, where=f"class {name!r}")
    is_a = body.get("is_a")
    if is_a is not None and not isinstance(is_a, str):
        raise OntologyDefinitionError(f"class {name!r} is_a must be a class name")
    properties = tuple(
        _property_from_mapping(class_name=name, name=prop_name, data=prop_body)
        for prop_name, prop_body in _body(data=body.get("properties"), where=f"{name}.properties").items()
    )
    return OntologyClass(
        name=name,
        is_a=is_a,
        properties=properties,
        closed=bool(body.get("closed", False)),
        description=str(body.get("description", "")),
    )


def _property_from_mapping(*, class_name: str, name: str, data: object) -> PropertySpec:
    where = f"property {class_name}.{name}"
    body = _body(data=data, where=where)
    _refuse_unknown_keys(data=body, allowed=_PROPERTY_KEYS, where=where)
    raw_type = body.get("type")
    try:
        prop_type = PropertyType(str(raw_type))
    except ValueError as exc:
        choices = ", ".join(PropertyType)
        raise OntologyDefinitionError(f"{where} has type {raw_type!r}; expected one of {choices}") from exc
    allowed = body.get("allowed") or ()
    if not isinstance(allowed, list | tuple):
        raise OntologyDefinitionError(f"{where} allowed must be a list")
    return PropertySpec(
        name=name,
        type=prop_type,
        required=bool(body.get("required", False)),
        allowed=tuple(str(value) for value in allowed),
        description=str(body.get("description", "")),
    )


def _relation_from_mapping(*, name: str, data: object) -> RelationSpec:
    where = f"relation {name!r}"
    body = _body(data=data, where=where)
    _refuse_unknown_keys(data=body, allowed=_RELATION_KEYS, where=where)
    source, target = body.get("from"), body.get("to")
    if not isinstance(source, str) or not isinstance(target, str):
        raise OntologyDefinitionError(f"{where} needs 'from' and 'to' class names")
    max_per_source = body.get("max_per_source")
    if max_per_source is not None and not _is_integer(max_per_source):
        raise OntologyDefinitionError(f"{where} max_per_source must be an integer")
    return RelationSpec(
        name=name,
        source=source,
        target=target,
        max_per_source=max_per_source,
        description=str(body.get("description", "")),
    )


def _refuse_unknown_keys(*, data: Mapping[str, object], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise OntologyDefinitionError(f"{where} has unknown keys: {', '.join(unknown)}")
