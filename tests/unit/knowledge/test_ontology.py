"""SPEC-27: the ontology model and entity/relation validation."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from cemaf.knowledge.models import KGEntity, KGRelation
from cemaf.knowledge.ontology import (
    Ontology,
    OntologyClass,
    OntologyDefinitionError,
    OntologyViolation,
    PropertySpec,
    PropertyType,
    RelationSpec,
    ViolationKind,
)


def service_catalog() -> Ontology:
    """The SPEC-27 service-catalog example, plus a Person-to-Person relation."""
    return Ontology(
        name="service-catalog",
        version=1,
        classes=(
            OntologyClass(
                name="Person",
                properties=(PropertySpec(name="email", type=PropertyType.STRING, required=True),),
            ),
            OntologyClass(name="Engineer", is_a="Person"),
            OntologyClass(name="Team", properties=(PropertySpec(name="channel", type=PropertyType.STRING),)),
            OntologyClass(
                name="Service",
                properties=(
                    PropertySpec(
                        name="tier",
                        type=PropertyType.STRING,
                        required=True,
                        allowed=("critical", "standard", "experimental"),
                    ),
                ),
            ),
        ),
        relations=(
            RelationSpec(name="member_of", source="Engineer", target="Team"),
            RelationSpec(name="owns", source="Team", target="Service"),
            RelationSpec(name="on_call_for", source="Engineer", target="Service", max_per_source=3),
            RelationSpec(name="mentors", source="Person", target="Person"),
        ),
    )


@pytest.fixture
def catalog() -> Ontology:
    return service_catalog()


def _kinds(violations: tuple[OntologyViolation, ...]) -> list[ViolationKind]:
    return [violation.kind for violation in violations]


class TestModel:
    def test_lookups_and_inheritance(self, catalog: Ontology) -> None:
        email = PropertySpec(name="email", type=PropertyType.STRING, required=True)

        assert catalog.is_a(class_name="Engineer", ancestor="Person")
        assert not catalog.is_a(class_name="Person", ancestor="Engineer")
        assert catalog.properties_of(class_name="Engineer") == (email,)
        assert catalog.descendants(class_name="Person") == ("Engineer",)
        assert catalog.relation_named(name="owns") == RelationSpec(
            name="owns", source="Team", target="Service"
        )
        assert catalog.class_named(name="Spaceship") is None

    def test_the_ontology_is_hashable_and_frozen(self, catalog: Ontology) -> None:
        assert hash(catalog) == hash(service_catalog())
        assert catalog == service_catalog()
        with pytest.raises(AttributeError):
            catalog.version = 2  # type: ignore[misc]


class TestDefinitionErrors:
    @staticmethod
    def _build(*classes: OntologyClass, relations: tuple[RelationSpec, ...] = ()) -> Ontology:
        return Ontology(name="o", version=1, classes=classes, relations=relations)

    def test_an_inheritance_cycle_is_refused(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="inheritance cycle: Engineer -> Engineer"):
            self._build(OntologyClass(name="Engineer", is_a="Engineer"))

    def test_a_longer_cycle_is_refused(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="inheritance cycle"):
            self._build(
                OntologyClass(name="A", is_a="B"),
                OntologyClass(name="B", is_a="C"),
                OntologyClass(name="C", is_a="A"),
            )

    def test_is_a_to_an_unknown_class_is_refused(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="unknown class 'Human'"):
            self._build(OntologyClass(name="Engineer", is_a="Human"))

    def test_a_relation_to_an_unknown_class_is_refused(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="to unknown class 'Service'"):
            self._build(
                OntologyClass(name="Team"),
                relations=(RelationSpec(name="owns", source="Team", target="Service"),),
            )

    def test_duplicate_names_are_refused(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="duplicate class name 'Team'"):
            self._build(OntologyClass(name="Team"), OntologyClass(name="Team"))
        with pytest.raises(OntologyDefinitionError, match="duplicate relation name 'r'"):
            self._build(
                OntologyClass(name="T"),
                relations=(
                    RelationSpec(name="r", source="T", target="T"),
                    RelationSpec(name="r", source="T", target="T"),
                ),
            )
        with pytest.raises(OntologyDefinitionError, match="duplicate property of 'T' name 'p'"):
            prop = PropertySpec(name="p", type=PropertyType.STRING)
            self._build(OntologyClass(name="T", properties=(prop, prop)))

    def test_allowed_values_need_a_string_property(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="not string"):
            self._build(
                OntologyClass(
                    name="S", properties=(PropertySpec(name="n", type=PropertyType.INTEGER, allowed=("1",)),)
                )
            )

    def test_max_per_source_must_be_at_least_one(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="at least 1"):
            self._build(
                OntologyClass(name="S"),
                relations=(RelationSpec(name="r", source="S", target="S", max_per_source=0),),
            )

    def test_a_subclass_cannot_retype_an_inherited_property(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="redeclares inherited property 'email'"):
            self._build(
                OntologyClass(
                    name="Person", properties=(PropertySpec(name="email", type=PropertyType.STRING),)
                ),
                OntologyClass(
                    name="Engineer",
                    is_a="Person",
                    properties=(PropertySpec(name="email", type=PropertyType.INTEGER),),
                ),
            )

    def test_a_subclass_may_tighten_an_inherited_property_of_the_same_type(self) -> None:
        tightened = PropertySpec(name="email", type=PropertyType.STRING, required=True)
        ontology = self._build(
            OntologyClass(name="Person", properties=(PropertySpec(name="email", type=PropertyType.STRING),)),
            OntologyClass(name="Engineer", is_a="Person", properties=(tightened,)),
        )

        assert ontology.properties_of(class_name="Engineer") == (tightened,)


class TestEntityValidation:
    def test_a_conforming_entity_has_no_violations(self, catalog: Ontology) -> None:
        service = KGEntity(id="svc-1", type="Service", name="Billing", properties={"tier": "critical"})

        assert catalog.validate_entity(entity=service) == ()

    def test_a_missing_required_property(self, catalog: Ontology) -> None:
        violations = catalog.validate_entity(entity=KGEntity(id="svc-1", type="Service", name="Billing"))

        assert _kinds(violations) == [ViolationKind.MISSING_PROPERTY]
        assert violations[0].subject_id == "svc-1"
        assert "tier" in violations[0].message

    def test_a_none_value_counts_as_absent(self, catalog: Ontology) -> None:
        service = KGEntity(id="svc-1", type="Service", name="Billing", properties={"tier": None})

        assert _kinds(catalog.validate_entity(entity=service)) == [ViolationKind.MISSING_PROPERTY]

    def test_an_inherited_required_property_is_checked(self, catalog: Ontology) -> None:
        engineer = KGEntity(id="eng-1", type="Engineer", name="Ada")

        assert _kinds(catalog.validate_entity(entity=engineer)) == [ViolationKind.MISSING_PROPERTY]

    def test_entity_fields_are_not_properties(self, catalog: Ontology) -> None:
        person = KGEntity(id="p-1", type="Person", name="Ada", properties={"email": "ada@example.com"})

        assert catalog.validate_entity(entity=person) == ()

    def test_a_value_outside_the_allowed_list(self, catalog: Ontology) -> None:
        service = KGEntity(id="svc-1", type="Service", name="Billing", properties={"tier": "legendary"})

        assert _kinds(catalog.validate_entity(entity=service)) == [ViolationKind.VALUE_NOT_ALLOWED]

    def test_a_wrongly_typed_value(self, catalog: Ontology) -> None:
        service = KGEntity(id="svc-1", type="Service", name="Billing", properties={"tier": 1})

        assert _kinds(catalog.validate_entity(entity=service)) == [ViolationKind.WRONG_PROPERTY_TYPE]

    def test_an_unknown_class(self, catalog: Ontology) -> None:
        violations = catalog.validate_entity(entity=KGEntity(id="x", type="Spaceship", name="X"))

        assert _kinds(violations) == [ViolationKind.UNKNOWN_CLASS]

    def test_an_open_class_accepts_undeclared_properties(self, catalog: Ontology) -> None:
        team = KGEntity(id="t-1", type="Team", name="Payments", properties={"colour": "teal"})

        assert catalog.validate_entity(entity=team) == ()

    def test_a_closed_class_reports_each_undeclared_property(self) -> None:
        ontology = Ontology(
            name="o",
            version=1,
            classes=(
                OntologyClass(
                    name="Base", properties=(PropertySpec(name="owner", type=PropertyType.STRING),)
                ),
                OntologyClass(
                    name="Service",
                    is_a="Base",
                    closed=True,
                    properties=(PropertySpec(name="tier", type=PropertyType.STRING),),
                ),
            ),
        )
        service = KGEntity(
            id="svc-1",
            type="Service",
            name="Billing",
            properties={"tier": "critical", "owner": "payments", "colour": "teal", "size": 3},
        )

        violations = ontology.validate_entity(entity=service)

        assert _kinds(violations) == [ViolationKind.UNKNOWN_PROPERTY, ViolationKind.UNKNOWN_PROPERTY]
        assert ["colour" in violations[0].message, "size" in violations[1].message] == [True, True]

    def test_each_broken_rule_is_one_violation(self, catalog: Ontology) -> None:
        ontology = Ontology(
            name="o",
            version=1,
            classes=(
                OntologyClass(
                    name="Service",
                    properties=(
                        PropertySpec(name="tier", type=PropertyType.STRING, required=True),
                        PropertySpec(name="replicas", type=PropertyType.INTEGER),
                    ),
                ),
            ),
        )
        service = KGEntity(id="svc-1", type="Service", name="Billing", properties={"replicas": "two"})

        assert _kinds(ontology.validate_entity(entity=service)) == [
            ViolationKind.MISSING_PROPERTY,
            ViolationKind.WRONG_PROPERTY_TYPE,
        ]


class TestPropertyTypes:
    @pytest.mark.parametrize(
        ("prop_type", "good", "bad"),
        [
            (PropertyType.STRING, "x", 1),
            (PropertyType.INTEGER, 3, True),
            (PropertyType.INTEGER, -1, 1.5),
            (PropertyType.NUMBER, 1.5, False),
            (PropertyType.NUMBER, 2, "2"),
            (PropertyType.BOOLEAN, False, 0),
            (PropertyType.DATE, date(2026, 11, 26), datetime(2026, 11, 26, 9, 0)),
            (PropertyType.DATE, "2026-11-26", "26/11/2026"),
            (PropertyType.DATETIME, datetime(2026, 11, 26, 9, 0), date(2026, 11, 26)),
            (PropertyType.DATETIME, "2026-11-26T09:00:00+00:00", "tomorrow"),
            (PropertyType.LIST, ("a", "b"), "ab"),
            (PropertyType.LIST, ["a"], {"a": 1}),
            (PropertyType.OBJECT, {"a": 1}, [("a", 1)]),
        ],
    )
    def test_values_fit_or_break_their_type(self, prop_type: PropertyType, good: object, bad: object) -> None:
        ontology = Ontology(
            name="o",
            version=1,
            classes=(OntologyClass(name="Thing", properties=(PropertySpec(name="v", type=prop_type),)),),
        )

        def check(value: object) -> list[ViolationKind]:
            return _kinds(
                ontology.validate_entity(
                    entity=KGEntity(id="t", type="Thing", name="t", properties={"v": value})
                )
            )

        assert check(good) == []
        assert check(bad) == [ViolationKind.WRONG_PROPERTY_TYPE]


class TestRelationValidation:
    @staticmethod
    def _entities() -> dict[str, KGEntity]:
        return {
            "eng": KGEntity(id="eng-1", type="Engineer", name="Ada"),
            "person": KGEntity(id="p-1", type="Person", name="Grace"),
            "team": KGEntity(id="team-1", type="Team", name="Payments"),
            "svc": KGEntity(id="svc-1", type="Service", name="Billing"),
        }

    def test_a_conforming_relation_has_no_violations(self, catalog: Ontology) -> None:
        e = self._entities()
        relation = KGRelation(source_id="team-1", target_id="svc-1", type="owns")

        violations = catalog.validate_relation(
            relation=relation, source=e["team"], target=e["svc"], existing_from_source=0
        )

        assert violations == ()

    def test_endpoints_qualify_through_inheritance(self, catalog: Ontology) -> None:
        e = self._entities()
        relation = KGRelation(source_id="eng-1", target_id="p-1", type="mentors")

        violations = catalog.validate_relation(
            relation=relation, source=e["eng"], target=e["person"], existing_from_source=0
        )

        assert violations == ()

    def test_a_relation_between_the_wrong_classes(self, catalog: Ontology) -> None:
        e = self._entities()
        relation = KGRelation(source_id="svc-1", target_id="team-1", type="owns")

        violations = catalog.validate_relation(
            relation=relation, source=e["svc"], target=e["team"], existing_from_source=0
        )

        assert _kinds(violations) == [ViolationKind.WRONG_SOURCE_CLASS, ViolationKind.WRONG_TARGET_CLASS]
        assert violations[0].subject_id == "svc-1->team-1:owns"

    def test_a_parent_does_not_qualify_for_a_subclass_end(self, catalog: Ontology) -> None:
        e = self._entities()
        relation = KGRelation(source_id="p-1", target_id="team-1", type="member_of")

        violations = catalog.validate_relation(
            relation=relation, source=e["person"], target=e["team"], existing_from_source=0
        )

        assert _kinds(violations) == [ViolationKind.WRONG_SOURCE_CLASS]

    def test_a_missing_endpoint_never_reveals_whether_it_exists(self, catalog: Ontology) -> None:
        relation = KGRelation(source_id="team-1", target_id="svc-9", type="owns")

        violations = catalog.validate_relation(
            relation=relation, source=self._entities()["team"], target=None, existing_from_source=0
        )

        assert _kinds(violations) == [ViolationKind.MISSING_ENDPOINT]
        assert violations[0].message == "target svc-9 not found or not visible"

    def test_an_unknown_relation(self, catalog: Ontology) -> None:
        e = self._entities()
        relation = KGRelation(source_id="team-1", target_id="svc-1", type="admires")

        violations = catalog.validate_relation(
            relation=relation, source=e["team"], target=e["svc"], existing_from_source=0
        )

        assert _kinds(violations) == [ViolationKind.UNKNOWN_RELATION]

    @pytest.mark.parametrize(("existing", "expected"), [(2, []), (3, [ViolationKind.TOO_MANY_RELATIONS])])
    def test_cardinality_counts_existing_outgoing_relations(
        self, catalog: Ontology, existing: int, expected: list[ViolationKind]
    ) -> None:
        e = self._entities()
        relation = KGRelation(source_id="eng-1", target_id="svc-1", type="on_call_for")

        violations = catalog.validate_relation(
            relation=relation, source=e["eng"], target=e["svc"], existing_from_source=existing
        )

        assert _kinds(violations) == expected


class TestInheritanceConsistency:
    """Property 3, checked over every class pair of a deep hierarchy with siblings."""

    @staticmethod
    def _hierarchy() -> Ontology:
        classes = [OntologyClass(name="L0", properties=(PropertySpec(name="p0", type=PropertyType.STRING),))]
        for depth in range(1, 6):
            for branch in ("a", "b"):
                parent = "L0" if depth == 1 else f"L{depth - 1}a"
                classes.append(
                    OntologyClass(
                        name=f"L{depth}{branch}",
                        is_a=parent,
                        properties=(PropertySpec(name=f"p{depth}{branch}", type=PropertyType.INTEGER),),
                    )
                )
        return Ontology(name="deep", version=1, classes=tuple(classes))

    def test_is_a_is_reflexive_and_transitive_and_properties_are_inherited(self) -> None:
        ontology = self._hierarchy()
        names = [cls.name for cls in ontology.classes]

        for child in names:
            assert ontology.is_a(class_name=child, ancestor=child)
            lineage = ontology.ancestors(class_name=child)
            for ancestor in lineage:
                assert ontology.is_a(class_name=child, ancestor=ancestor)
                assert set(ontology.properties_of(class_name=ancestor)) <= set(
                    ontology.properties_of(class_name=child)
                )
                assert child in ontology.descendants(class_name=ancestor)
            for other in names:
                if other != child and other not in lineage:
                    assert not ontology.is_a(class_name=child, ancestor=other)

    def test_ancestors_are_nearest_first(self) -> None:
        assert self._hierarchy().ancestors(class_name="L3b") == ("L2a", "L1a", "L0")

    def test_an_unknown_class_is_nothing(self) -> None:
        ontology = self._hierarchy()

        assert not ontology.is_a(class_name="Ghost", ancestor="Ghost")
        assert ontology.ancestors(class_name="Ghost") == ()
        assert ontology.properties_of(class_name="Ghost") == ()
