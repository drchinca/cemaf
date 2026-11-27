"""SPEC-27: loading an ontology from YAML, JSON or a mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from cemaf.knowledge.ontology import (
    OntologyClass,
    OntologyDefinitionError,
    load_ontology,
    ontology_from_mapping,
)
from tests.unit.knowledge.test_ontology import service_catalog

SERVICE_CATALOG_YAML = """\
ontology: service-catalog
version: 1
classes:
  Person:
    properties:
      email: {type: string, required: true}
  Engineer: {is_a: Person}
  Team:
    properties:
      channel: {type: string}
  Service:
    properties:
      tier: {type: string, required: true, allowed: [critical, standard, experimental]}
relations:
  member_of: {from: Engineer, to: Team}
  owns: {from: Team, to: Service}
  on_call_for: {from: Engineer, to: Service, max_per_source: 3}
  mentors: {from: Person, to: Person}
"""


class TestLoading:
    def test_yaml_loads_the_same_ontology_as_the_python_built_one(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.yaml"
        path.write_text(SERVICE_CATALOG_YAML)

        loaded = load_ontology(path=path)

        assert loaded == service_catalog()
        assert loaded.is_a(class_name="Engineer", ancestor="Person")
        assert [prop.name for prop in loaded.properties_of(class_name="Engineer")] == ["email"]

    def test_json_loads_the_same_ontology(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(yaml.safe_load(SERVICE_CATALOG_YAML)))

        assert load_ontology(path=path) == service_catalog()

    def test_a_class_with_no_body_is_an_empty_open_class(self) -> None:
        ontology = ontology_from_mapping(data={"ontology": "o", "version": 1, "classes": {"Note": None}})

        assert ontology.class_named(name="Note") == OntologyClass(name="Note")


class TestMalformedDefinitions:
    def test_an_inheritance_cycle_is_refused(self) -> None:
        with pytest.raises(OntologyDefinitionError, match="inheritance cycle: Engineer -> Engineer"):
            ontology_from_mapping(
                data={"ontology": "o", "version": 1, "classes": {"Engineer": {"is_a": "Engineer"}}}
            )

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            ({"classes": {"Engineer": {"is_a": "Human"}}}, "unknown class 'Human'"),
            (
                {"classes": {"Team": {}}, "relations": {"owns": {"from": "Team", "to": "Service"}}},
                "to unknown class",
            ),
            ({"classes": {"Team": {}}, "relations": {"owns": {"from": "Team"}}}, "needs 'from' and 'to'"),
            ({"classes": {"S": {"properties": {"n": {"type": "integer", "allowed": ["1"]}}}}}, "not string"),
            ({"classes": {"S": {"properties": {"n": {"type": "colour"}}}}}, "expected one of"),
            ({"classes": {"S": {"colour": "red"}}}, "unknown keys: colour"),
            (
                {"classes": {"S": {}}, "relations": {"r": {"from": "S", "to": "S", "max_per_source": 0}}},
                "at least 1",
            ),
            (
                {"classes": {"S": {}}, "relations": {"r": {"from": "S", "to": "S", "max_per_source": "3"}}},
                "integer",
            ),
            ({"classes": ["S"]}, "must be a mapping"),
        ],
    )
    def test_a_malformed_definition_names_its_problem(self, data: dict[str, object], message: str) -> None:
        with pytest.raises(OntologyDefinitionError, match=message):
            ontology_from_mapping(data={"ontology": "o", "version": 1, **data})

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            ({"version": 1, "classes": {}}, "'ontology' must be"),
            ({"ontology": "o", "version": "1", "classes": {}}, "'version' must be an integer"),
            ({"ontology": "o", "version": True, "classes": {}}, "'version' must be an integer"),
            ({"ontology": "o", "version": 1, "rules": {}}, "unknown keys: rules"),
        ],
    )
    def test_a_malformed_header_is_refused(self, data: dict[str, object], message: str) -> None:
        with pytest.raises(OntologyDefinitionError, match=message):
            ontology_from_mapping(data=data)

    def test_a_subclass_cannot_retype_an_inherited_property(self) -> None:
        classes = {
            "Person": {"properties": {"email": {"type": "string"}}},
            "Engineer": {"is_a": "Person", "properties": {"email": {"type": "integer"}}},
        }
        with pytest.raises(OntologyDefinitionError, match="redeclares inherited property 'email'"):
            ontology_from_mapping(data={"ontology": "o", "version": 1, "classes": classes})

    @pytest.mark.parametrize(
        ("filename", "content", "message"),
        [
            ("o.toml", "x = 1", r"\.yaml, \.yml or \.json"),
            ("o.yaml", "classes: [unclosed", "not valid YAML"),
            ("o.json", "{", "not valid JSON"),
            ("o.yaml", "- just\n- a list\n", "mapping at the top level"),
        ],
    )
    def test_a_bad_file_is_refused(self, tmp_path: Path, filename: str, content: str, message: str) -> None:
        path = tmp_path / filename
        path.write_text(content)
        with pytest.raises(OntologyDefinitionError, match=message):
            load_ontology(path=path)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(OntologyDefinitionError, match="cannot read ontology"):
            load_ontology(path=tmp_path / "absent.yaml")
