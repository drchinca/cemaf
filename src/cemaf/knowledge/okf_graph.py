"""Project OKF snapshots through the existing KnowledgeGraph protocol."""

from dataclasses import dataclass

from cemaf.knowledge.models import EntityType, KGEntity, KGRelation, RelationType
from cemaf.knowledge.okf import OKFBundle
from cemaf.knowledge.protocols import KnowledgeGraph


@dataclass(frozen=True)
class OKFImportResult:
    entity_count: int
    relation_count: int
    unresolved_links: tuple[tuple[str, str], ...]
    revision: str


async def import_okf_bundle(bundle: OKFBundle, *, graph: KnowledgeGraph, bundle_id: str) -> OKFImportResult:
    """Import a snapshot into an unused namespace of any graph backend.

    All concept types map to CONCEPT with their exact type in ``okf_type``.
    Plain links become REFERENCES; local provenance sources become
    EXTRACTED_FROM. Broken links are reported without inventing entities.
    Use a new namespace or backend branch for each subsequent snapshot;
    this function does not implement synchronization or graph transactions.
    """
    revision = bundle.revision
    documents = {doc.concept_id: doc for doc in bundle.documents}
    entities = []
    relations: dict[tuple[str, str, RelationType], KGRelation] = {}
    unresolved: set[tuple[str, str]] = set()
    # Build and validate everything before the first graph write.
    for document in bundle.documents:
        source_id = document.source_id(bundle_id=bundle_id)
        entities.append(
            KGEntity(
                id=source_id,
                type=EntityType.CONCEPT,
                name=document.title,
                description=str(document.frontmatter.get("description", "")),
                properties={
                    **document.metadata(bundle_id=bundle_id, revision=revision),
                    "content": document.render(),
                },
            )
        )
        links = [(href, RelationType.REFERENCES) for href in document.links()]
        sources = document.frontmatter.get("sources", [])
        if isinstance(sources, list):
            links.extend(
                (source["resource"], RelationType.EXTRACTED_FROM)
                for source in sources
                if isinstance(source, dict) and isinstance(source.get("resource"), str)
            )
        for href, relation_type in links:
            target = document.resolve_link(href)
            if target is None:
                continue
            if target not in documents:
                unresolved.add((document.concept_id, href))
                continue
            target_id = documents[target].source_id(bundle_id=bundle_id)
            relations[source_id, target_id, relation_type] = KGRelation(
                source_id=source_id,
                target_id=target_id,
                type=relation_type,
                properties={"bundle_revision": revision, "href": href},
            )
    for entity in entities:
        if await graph.get_entity(entity.id) is not None:
            raise ValueError(f"OKF import requires an unused namespace: {entity.id}")
    for entity in entities:
        await graph.add_entity(entity)
    for relation in relations.values():
        await graph.add_relation(relation)
    return OKFImportResult(len(entities), len(relations), tuple(sorted(unresolved)), revision)
