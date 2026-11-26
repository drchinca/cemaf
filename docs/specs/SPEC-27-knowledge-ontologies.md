---
title: Knowledge Ontologies
spec_id: SPEC-27
status: Draft
last_reviewed: 2026-11-26
owner: drchinca
parent: SPEC-02 — KG and DataSource services
depends_on: [SPEC-02, SPEC-07]
---

# SPEC-27: Knowledge Ontologies

> An ontology tells CEMAF what a knowledge base is *about*: which kinds of things
> exist, what they carry, how they may relate, and which rules the knowledge
> should obey. It turns the knowledge graph (KG) from CEMAF's self-model into an
> engine for any domain's knowledge base.

## 1. Context

The knowledge graph accepts only a fixed vocabulary: `EntityType` (`agent`, `tool`,
`dag`, `run`, `module`, `protocol`, `skill`, `concept`) and `RelationType` (`uses`,
`produces`, `depends_on`, …). That vocabulary describes CEMAF itself. Another
domain's knowledge base — *a Service is owned by a Team*, *a Document is written by
an Author* — cannot be expressed, checked, or queried by meaning.

An **ontology** is a versioned, declared vocabulary for one knowledge base:

- **classes** — kinds of things, with single inheritance (`Engineer is_a Person`);
- **properties** — named, typed attributes a class carries, optionally required or
  limited to allowed values; subclasses inherit them;
- **relations** — named links with a source class and a target class
  (`owns: Team → Service`) and optional cardinality limits.

Enforcement is **advisory**: knowledge that breaks the ontology is still written,
and every break is recorded as an `OntologyViolation` and published as an event.
Messy real-world extraction keeps flowing; the violations show where it is wrong.

CEMAF's own vocabulary becomes one ontology, `cemaf-self`, so the self-hosting
layer runs on the same machinery as any other knowledge base.

```mermaid
flowchart LR
  Y[ontology.yaml] --> L[load_ontology]
  P[Python declaration] --> L
  L --> O[Ontology]
  O --> G[OntologyKnowledgeGraph]
  W[add_entity / add_relation] --> G
  G -->|always writes| K[(KnowledgeGraph)]
  G -->|breaks a rule| V[OntologyViolation + ONTOLOGY_VIOLATION event]
  Q[entities_of_class / related] --> G
```

## 2. Interface Contract (MDE)

```python
class PropertyType(StrEnum):
    STRING; INTEGER; NUMBER; BOOLEAN; DATE; DATETIME; LIST; OBJECT
    # DATE accepts datetime.date or an ISO-8601 date string (YAML's parsed dates included);
    # DATETIME accepts datetime.datetime or an ISO-8601 datetime string; BOOLEAN is not an
    # INTEGER; LIST = list/tuple; OBJECT = mapping.

@dataclass(frozen=True, slots=True)
class PropertySpec:
    name: str
    type: PropertyType
    required: bool = False
    allowed: tuple[str, ...] = ()          # STRING only; empty = any string. On another type
                                            # it is an OntologyDefinitionError.
    description: str = ""

@dataclass(frozen=True, slots=True)
class OntologyClass:
    name: str
    is_a: str | None = None
    properties: tuple[PropertySpec, ...] = ()   # tuples keep every ontology type hashable
    closed: bool = False                    # True: properties the class (and its ancestors)
                                            # don't declare are UNKNOWN_PROPERTY violations.
                                            # False (default): they are allowed.
    description: str = ""

@dataclass(frozen=True, slots=True)
class RelationSpec:
    name: str
    source: str                             # class name; subclasses also qualify
    target: str
    max_per_source: int | None = None       # e.g. a Service has at most 1 owning Team
    description: str = ""

@dataclass(frozen=True, slots=True)
class Ontology:
    name: str
    version: int
    classes: tuple[OntologyClass, ...]
    relations: tuple[RelationSpec, ...]
    def class_named(self, *, name: str) -> OntologyClass | None: ...
    def relation_named(self, *, name: str) -> RelationSpec | None: ...
    def ancestors(self, *, class_name: str) -> tuple[str, ...]: ...      # nearest first
    def is_a(self, *, class_name: str, ancestor: str) -> bool: ...
    def properties_of(self, *, class_name: str) -> tuple[PropertySpec, ...]: ...  # ancestors' first, then own
    def validate_entity(self, *, entity: KGEntity) -> tuple[OntologyViolation, ...]: ...
    def validate_relation(self, *, relation: KGRelation, source: KGEntity | None,
                          target: KGEntity | None, existing_from_source: int,
                          ) -> tuple[OntologyViolation, ...]: ...
        # source/target None = not found. existing_from_source counts the source's OUTGOING
        # relations of this type, excluding one with the same (source, target, type) key.

class ViolationKind(StrEnum):
    UNKNOWN_CLASS; MISSING_PROPERTY; UNKNOWN_PROPERTY; WRONG_PROPERTY_TYPE; VALUE_NOT_ALLOWED
    UNKNOWN_RELATION; WRONG_SOURCE_CLASS; WRONG_TARGET_CLASS; MISSING_ENDPOINT; TOO_MANY_RELATIONS

@dataclass(frozen=True, slots=True)
class OntologyViolation:
    kind: ViolationKind
    subject_id: str                         # entity id, or "source->target:relation"
    message: str

def load_ontology(*, path: Path) -> Ontology: ...          # .yaml/.yml (pyyaml, imported lazily from the
                                                           # okf extra) or .json; OntologyDefinitionError
def ontology_from_mapping(*, data: Mapping[str, object]) -> Ontology: ...
# Python code builds an Ontology directly from the dataclasses, or via ontology_from_mapping.

class OntologyDefinitionError(ValueError): ...             # the ontology itself is malformed

class OntologyKnowledgeGraph:                               # implements KnowledgeGraph
    def __init__(self, *, graph: KnowledgeGraph, ontology: Ontology,
                 event_bus: EventBus | None = None, recent_violation_limit: int = 1_000) -> None: ...
    @property
    def ontology(self) -> Ontology: ...
    def recent_violations(self) -> tuple[OntologyViolation, ...]: ...   # last N; events carry all
    async def entities_of_class(self, *, class_name: str, include_subclasses: bool = True) -> tuple[KGEntity, ...]: ...
        # exhaustive: entities_of_type for the class and each descendant, not text search
    async def related(self, *, entity_id: str, relation: str) -> tuple[KGEntity, ...]: ...
        # OUTGOING relations of that type from entity_id, one hop
    # Every other KnowledgeGraph method delegates to `graph`; writes validate first, then
    # always write. capabilities() is passed through. Branching (BranchingKnowledgeGraph)
    # is not exposed by the wrapper.

# KnowledgeGraph protocol gains two methods. Implementations: MemoryBackedKnowledgeGraph,
# HubKnowledgeGraph and SpokeReadHubWriteKG (both delegate), and every test double.
    async def entities_of_type(self, *, entity_type: str) -> tuple[KGEntity, ...]: ...
        # every visible entity of exactly that type; no limit, no ranking
    async def relations_from(self, *, entity_id: str, relation_type: str | None = None,
                             ) -> tuple[KGRelation, ...]: ...
        # visible relations whose source is entity_id, whatever the target's visibility.
        # MemoryBackedKnowledgeGraph reads the entity's relation index (kg:index:<id>).
        # The wrapper's cardinality count is len(relations_from(...)) minus the relation
        # being written if it already exists.

# So entities_of_type can be exhaustive, a prefix scan is added at each memory layer:
#   MemoryManager.list_by_prefix        -> delegates to its SemanticMemoryStore
#   SemanticMemoryStore.list_by_prefix  -> DefaultSemanticMemoryStore filters its
#                                          MemoryStore.list_by_scope(scope) by key prefix;
#                                          TieredMemoryStore delegates to its inner store
    async def list_by_prefix(self, *, scope: MemoryScope, key_prefix: str) -> tuple[MemoryItem, ...]: ...
        # every stored item in scope whose key starts with key_prefix; a full scan of the
        # scope, no result limit. Every MemoryStore already has list_by_scope.

CEMAF_SELF_ONTOLOGY: Ontology
    # Root class "thing"; every EntityType value is a class with is_a="thing" (all open).
    # Every RelationType value is a relation from "thing" to "thing".
    # "dag" declares the properties CEMAF writes when versioning a solution
    # (meta/agents.py): version STRING, use_case STRING, roles LIST, node_count INTEGER,
    # constraints OBJECT.

KGEntity.type: str              # was EntityType; EntityType (a StrEnum) still fits as a class name
KGRelation.type: str            # was RelationType
# Filters typed EntityType / RelationType take str: KnowledgeGraph.search and
# query_neighbors, hub_spoke.py, meta/tools.py. Reading back an entity or relation keeps
# the stored string (graph.py no longer calls EntityType(...) / RelationType(...)).
# `.type.value` becomes `.type` in models.py (to_dict), graph.py (relation key),
# interceptors/pull.py and meta/tools.py.
# meta/tools.py accepts any type string: no rejection of names outside the enums, and a
# given type filters exactly; only an empty or missing filter means "no filter".

EventType.ONTOLOGY_VIOLATION    # payload: {"ontology", "version", "kind", "subject_id", "message"}
```

YAML form (the same structure `ontology_from_mapping` accepts):

```yaml
ontology: service-catalog
version: 1
classes:
  Person:
    properties:
      name: {type: string, required: true}
  Engineer: {is_a: Person}
  Team:
    properties:
      name: {type: string, required: true}
  Service:
    properties:
      tier: {type: string, required: true, allowed: [critical, standard, experimental]}
relations:
  member_of: {from: Engineer, to: Team}
  owns: {from: Team, to: Service}
  on_call_for: {from: Engineer, to: Service, max_per_source: 3}
```

**Write semantics (no ambiguity):**
- Re-writing an entity re-validates the entity only; its existing relations are not re-checked.
- A relation written before an endpoint exists records `MISSING_ENDPOINT` for that end.
- An endpoint the graph does not return — absent, or above its clearance; the protocol
  cannot tell these apart — is a `MISSING_ENDPOINT` violation whose message says
  "not found or not visible", so existence is never revealed.
- A property value of `None` counts as absent.

## 3. Invariants (DbC)

1. `IF an ontology declares is_a to an unknown class, an inheritance cycle, a relation endpoint that is not a class, or a duplicate name, THEN load SHALL raise OntologyDefinitionError` naming the problem.
2. `properties_of(C) SHALL be C's own properties plus every ancestor's`; a subclass may not redeclare an inherited property with a different type.
3. `is_a(C, C) SHALL be True`, and `is_a` SHALL be transitive along `is_a` links.
4. `WHEN an entity or relation is written through OntologyKnowledgeGraph, THE System SHALL write it to the underlying graph whatever its violations` (advisory).
5. `WHEN a write breaks the ontology, THE System SHALL record one OntologyViolation per broken rule and, if an event bus is set, publish ONTOLOGY_VIOLATION for each.`
6. `A write that satisfies the ontology SHALL produce no violation and no event.`
7. `A relation's source and target SHALL qualify through inheritance`: an Engineer satisfies `from: Person`.
8. `WHEN a source already has max_per_source OUTGOING relations of a type, a further, different relation of that type SHALL be a TOO_MANY_RELATIONS violation`; re-writing an existing relation never is.
9. `entities_of_class(C, include_subclasses=True) SHALL return entities of C and of every descendant of C.`
10. `CEMAF_SELF_ONTOLOGY SHALL accept the entities and relations CEMAF actually writes` — the meta layer's solution versioning (`meta/agents.py`, list and mapping properties included) and OKF import produce no violations — and SHALL still catch a wrongly typed `dag` property (e.g. `node_count: "five"`), so the check is not vacuous.
11. `THE ontology SHALL be immutable and hashable` (frozen dataclasses holding tuples); a changed ontology is a new version.
12. `IF a class is closed, THEN a property neither it nor an ancestor declares SHALL be an UNKNOWN_PROPERTY violation`; open classes accept undeclared properties.
13. `entities_of_type SHALL return every visible entity of that type`, with no result limit.

Budget: 13 invariants.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Knowledge ontologies

  Scenario: Load an ontology from YAML
    Given the service-catalog YAML above
    When it is loaded
    Then Engineer is_a Person and Engineer has the required property "name"

  Scenario: A malformed ontology is refused
    Given an ontology where Engineer is_a Engineer
    When it is loaded
    Then OntologyDefinitionError names the inheritance cycle

  Scenario: A valid write is quiet
    Given a Service with tier "critical"
    When it is written
    Then it is stored and no violation is recorded

  Scenario: A missing required property is recorded, not rejected
    Given a Service with no tier
    When it is written
    Then it is stored and a MISSING_PROPERTY violation is recorded and published

  Scenario: A value outside the allowed list is recorded
    Given a Service with tier "legendary"
    When it is written
    Then a VALUE_NOT_ALLOWED violation is recorded

  Scenario: A relation between the wrong classes is recorded
    Given a Service and a Team
    When "owns" is written from the Service to the Team
    Then WRONG_SOURCE_CLASS and WRONG_TARGET_CLASS are recorded

  Scenario: Cardinality is checked
    Given an Engineer already on call for 3 Services
    When a 4th "on_call_for" relation is written
    Then a TOO_MANY_RELATIONS violation is recorded

  Scenario: Querying a class includes its subclasses
    Given a Person and an Engineer
    When entities_of_class("Person") runs
    Then both are returned

  Scenario: Walking a typed relation
    Given a Team that owns two Services
    When related(team, "owns") runs
    Then both Services are returned

  Scenario: Re-writing a relation is not a cardinality break
    Given an Engineer on call for 3 Services
    When one of those 3 relations is written again
    Then no violation is recorded

  Scenario: A closed class reports undeclared properties
    Given Service is closed
    When a Service with an undeclared "colour" property is written
    Then an UNKNOWN_PROPERTY violation is recorded

  Scenario: CEMAF's own knowledge fits its ontology
    Given the meta layer's solution-versioning step and an OKF import
    When they write to an OntologyKnowledgeGraph bound to CEMAF_SELF_ONTOLOGY
    Then no violation is recorded

  Scenario: The self-ontology still catches a broken write
    Given a dag entity whose node_count is "five"
    When it is written under CEMAF_SELF_ONTOLOGY
    Then a WRONG_PROPERTY_TYPE violation is recorded
```

Budget: 13 scenarios.

## 5. Out of Scope

- **Agent use of ontologies** — extraction guided by the ontology, and ontology-labelled
  context for agents — is SPEC-28, built on this spec.
- Importing OWL / RDF / SHACL / schema.org (a later adapter producing an `Ontology`).
- Multiple inheritance, reasoning beyond `is_a`, and rules across more than one relation.
- Strict (rejecting) enforcement.
- Ontology-checked branches (`BranchingKnowledgeGraph` through the wrapper).
- Incoming-relation traversal in `related()`.
- Migrating stored knowledge between ontology versions.

## 6. Dependencies

- `cemaf.knowledge.protocols.KnowledgeGraph`, `KGEntity`, `KGRelation` (SPEC-02/07).
- `cemaf.events` for `ONTOLOGY_VIOLATION`.
- `pyyaml` (already in the `okf` extra) for YAML loading; JSON needs nothing extra.

## 7. Correctness Properties

### Property 1: Advisory never loses knowledge
*For any* ontology and any write, the underlying graph receives the write.
**Validates: §3 Invariant 4; §4 "A missing required property is recorded, not rejected"**

### Property 2: Violations are exactly the broken rules
*For any* entity, the recorded violations are exactly the rules it breaks: none for a
conforming entity, one per broken rule otherwise.
**Validates: §3 Invariants 5, 6; §4 "A valid write is quiet", "A value outside the allowed list"**

### Property 3: Inheritance is consistent
*For any* class C with ancestor A: `is_a(C, A)`, `properties_of(C) ⊇ properties_of(A)`,
and every C entity is returned by `entities_of_class(A)`.
**Validates: §3 Invariants 2, 3, 7, 9**

## 9. Observability Contract

- **Event**: `ONTOLOGY_VIOLATION` with `{ontology, version, kind, subject_id, message}`.
- **Log**: `ontology.violation` at INFO per violation; `ontology.loaded` with class and
  relation counts.

## 10. Delivery plan

Four PRs, each under the size limit, each green on its own:

| PR | Contents |
|---|---|
| A | `KGEntity.type` / `KGRelation.type` → `str` at every site listed in §2; `list_by_prefix` on `MemoryManager` and `SemanticMemoryStore` (both implementations); `entities_of_type` and `relations_from` on the KG protocol and all three implementations |
| B | `Ontology` model, `PropertyType`, YAML/JSON loading, `OntologyDefinitionError`, inheritance, `validate_entity` / `validate_relation` |
| C | `OntologyKnowledgeGraph`, `ONTOLOGY_VIOLATION`, recent-violation window, cardinality counting, `entities_of_class`, `related` |
| D | `CEMAF_SELF_ONTOLOGY` and the real-write scenario over solution versioning and OKF import |

## 11. Test Coverage Update

- **Unit** (`tests/unit/knowledge/test_ontology.py`): loading, definition errors,
  inheritance, every `ViolationKind`, property-based inheritance checks (Property 3).
- **Integration** (`tests/integration/test_ontology_knowledge_graph.py`): §4 scenarios
  through a real `MemoryBackedKnowledgeGraph` and `InMemoryEventBus`, including the
  `cemaf-self` scenario over the real solution-versioning write and an OKF import.
