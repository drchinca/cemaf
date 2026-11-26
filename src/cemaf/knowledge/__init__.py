"""Knowledge graph module — entity/relation modeling and graph queries."""

from cemaf.knowledge.factories import create_knowledge_graph, knowledge_graph_registry
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.knowledge.hub_spoke import (
    KG_INVALIDATION_EVENT_TYPE,
    HubKnowledgeGraph,
    InvalidationKind,
    KGInvalidationEvent,
    LocalSpokeCache,
    SpokeCacheConfig,
    SpokeReadHubWriteKG,
    SpokeStats,
    create_hub_spoke_kg,
)
from cemaf.knowledge.models import (
    EntityType,
    KGBranchDiff,
    KGBranchRef,
    KGEntity,
    KGMergeResult,
    KGQueryResult,
    KGRelation,
    KnowledgeGraphCapabilities,
    RelationType,
)
from cemaf.knowledge.okf import OKFBundle, OKFBundleDiff, OKFDocument
from cemaf.knowledge.okf_graph import OKFImportResult, import_okf_bundle
from cemaf.knowledge.ontology import (
    Ontology,
    OntologyClass,
    OntologyDefinitionError,
    OntologyViolation,
    PropertySpec,
    PropertyType,
    RelationSpec,
    ViolationKind,
    load_ontology,
    ontology_from_mapping,
)
from cemaf.knowledge.ontology_graph import OntologyKnowledgeGraph
from cemaf.knowledge.protocols import (
    BranchingKnowledgeGraph,
    KnowledgeGraph,
    KnowledgeGraphCapabilitiesProvider,
)

__all__ = [
    # Ontologies (SPEC-27)
    "Ontology",
    "OntologyClass",
    "OntologyDefinitionError",
    "OntologyKnowledgeGraph",
    "OntologyViolation",
    "PropertySpec",
    "PropertyType",
    "RelationSpec",
    "ViolationKind",
    "load_ontology",
    "ontology_from_mapping",
    "OKFBundle",
    "OKFBundleDiff",
    "OKFDocument",
    "OKFImportResult",
    "import_okf_bundle",
    # Enums
    "EntityType",
    "InvalidationKind",
    "RelationType",
    # Data models
    "KGBranchDiff",
    "KGBranchRef",
    "KGEntity",
    "KGInvalidationEvent",
    "KGMergeResult",
    "KGQueryResult",
    "KGRelation",
    "KnowledgeGraphCapabilities",
    "SpokeCacheConfig",
    "SpokeStats",
    # Protocol
    "BranchingKnowledgeGraph",
    "KnowledgeGraph",
    "KnowledgeGraphCapabilitiesProvider",
    # Implementations
    "HubKnowledgeGraph",
    "LocalSpokeCache",
    "MemoryBackedKnowledgeGraph",
    "SpokeReadHubWriteKG",
    # Factories
    "create_hub_spoke_kg",
    "create_knowledge_graph",
    "knowledge_graph_registry",
    # Constants
    "KG_INVALIDATION_EVENT_TYPE",
]
