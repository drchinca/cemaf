"""Two offline research sessions with persisted retrieval and selective indexing.

Run: uv run python examples/app_shapes/okf_project_memory.py
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from cemaf.citation import CitationTracker
from cemaf.core.types import JSON
from cemaf.knowledge import OKFBundle, OKFDocument
from cemaf.retrieval.memory_store import MockEmbeddingProvider
from cemaf.retrieval.protocols import EmbeddingProvider
from cemaf.retrieval.sqlite_vector_store import SqliteVectorStore


async def run_sessions(directory: Path, *, embedding_provider: EmbeddingProvider | None = None) -> JSON:
    provider = embedding_provider or MockEmbeddingProvider()
    namespace = "research"
    fixture = Path(__file__).resolve().parents[1] / "data" / "okf_research"
    retired = OKFDocument(path="retired.md", frontmatter={"type": "Note"}, body="Superseded work item.")
    previous = OKFBundle.load(fixture).with_document(retired)
    previous_path = previous.write(directory / "session-1")
    database = str(directory / "retrieval.db")
    async with SqliteVectorStore(db_path=database, embedding_provider=provider) as store:
        await store.add_batch(
            [doc.to_document(bundle_id=namespace, revision=previous.revision) for doc in previous.documents]
        )

    # A later session reloads both accepted snapshots and the existing database.
    previous = OKFBundle.load(previous_path)
    selected = previous.get("findings/calibration")
    revised = selected.propose(
        body=selected.body + "\nAdditional review is requested.\n",
        actor="cemaf/research",
        run_id="offline-session-2",
    )
    # This local database is a draft workspace; proposals remain unverified.
    current = (
        previous.with_document(revised)
        .without_document("retired")
        .with_document(
            OKFDocument(
                path="next-experiment.md",
                frontmatter={"type": "Plan", "status": "draft"},
                body="Repeat the calibration under a second environmental condition.",
            )
        )
    )
    current = OKFBundle.load(current.write(directory / "session-2"))
    changes = current.diff(previous)
    changed_ids = (*changes.added, *changes.modified)
    async with SqliteVectorStore(db_path=database, embedding_provider=provider) as store:
        # Existing VectorStore operations own persistence and embeddings.
        for concept_id in changes.removed:
            await store.delete(previous.get(concept_id).source_id(bundle_id=namespace))
        await store.add_batch(
            [
                current.get(concept_id).to_document(bundle_id=namespace, revision=current.revision)
                for concept_id in changed_ids
            ]
        )
        assert await store.count() == len(current.documents)
        unchanged_id = current.get("protocols/calibration").source_id(bundle_id=namespace)
        unchanged = await store.get(unchanged_id)
        assert unchanged is not None
        # This is the snapshot at indexing time, not a fabricated latest revision.
        assert unchanged.metadata["bundle_revision"] == previous.revision
        results = await store.search_by_text("calibration", k=3)
        citations = CitationTracker().track_search_results(results)
        assert all(
            c.metadata["content_hash"] == current.get(c.metadata["concept_id"]).content_hash
            for c in citations
        )
        assert await store.get(retired.source_id(bundle_id=namespace)) is None
    print(f"Session 1: indexed {len(previous.documents)} concepts")
    print(f"Session 2: indexed {len(changed_ids)} changed concepts; removed {len(changes.removed)}")
    return {
        "initial_count": len(previous.documents),
        "changed_count": len(changed_ids),
        "removed_count": len(changes.removed),
        "citations": [c.to_dict() for c in citations],
    }


async def main() -> None:
    with TemporaryDirectory(prefix="cemaf-okf-memory-") as directory:
        await run_sessions(Path(directory))


if __name__ == "__main__":
    asyncio.run(main())
