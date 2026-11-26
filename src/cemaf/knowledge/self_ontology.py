"""CEMAF's own ontology: the classes and relations CEMAF writes about itself (SPEC-27)."""

from __future__ import annotations

from typing import Final

from cemaf.knowledge.models import EntityType, RelationType
from cemaf.knowledge.ontology import Ontology, OntologyClass, PropertySpec, PropertyType, RelationSpec

THING: Final = "thing"
SELF_ONTOLOGY_NAME: Final = "cemaf-self"
SELF_ONTOLOGY_VERSION: Final = 1

# The properties the meta layer writes when it versions a solution (meta/agents.py).
DAG_PROPERTIES: Final = (
    PropertySpec(name="version", type=PropertyType.STRING, description="Solution version tag"),
    PropertySpec(name="use_case", type=PropertyType.STRING, description="Problem the solution addresses"),
    PropertySpec(name="roles", type=PropertyType.LIST, description="Agent roles in the solution"),
    PropertySpec(name="node_count", type=PropertyType.INTEGER, description="Nodes in the designed DAG"),
    PropertySpec(name="constraints", type=PropertyType.OBJECT, description="Design constraints"),
)


def _class_for(*, entity_type: EntityType) -> OntologyClass:
    properties = DAG_PROPERTIES if entity_type is EntityType.DAG else ()
    return OntologyClass(name=str(entity_type), is_a=THING, properties=properties)


CEMAF_SELF_ONTOLOGY: Final = Ontology(
    name=SELF_ONTOLOGY_NAME,
    version=SELF_ONTOLOGY_VERSION,
    classes=(
        OntologyClass(name=THING, description="Anything CEMAF knows about"),
        *(_class_for(entity_type=entity_type) for entity_type in EntityType),
    ),
    relations=tuple(
        RelationSpec(name=str(relation), source=THING, target=THING) for relation in RelationType
    ),
)
