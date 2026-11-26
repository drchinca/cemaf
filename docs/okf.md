# Open Knowledge Format

CEMAF consumes and produces [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)
bundles: ordinary folders of Markdown concepts with YAML frontmatter and links.
The adapter supports the v0.2 document conventions and reads v0.1 concepts.
Knowledge stays readable outside CEMAF, while CEMAF supplies context budgets,
graph access, citations, execution, evaluation, and run provenance.

Install the optional parsers:

```bash
pip install 'cemaf[okf]'
```

## Discover first, load selected knowledge

For long-running research and project memory, keep the complete knowledge base
on disk and give each turn only a directory catalog and selected concepts.
Catalogs omit document bodies, list immediate children, and paginate at 50 entries
by default. Descend into a directory or advance `offset` when more detail is needed.

```python
from cemaf.knowledge import OKFBundle

bundle = OKFBundle.load("examples/data/okf_research")
print(bundle.catalog())
print(bundle.catalog("findings", offset=0, limit=20))
concept = bundle.get("findings/calibration")
```

`load` reads a filesystem snapshot into process memory; progressive disclosure
controls what enters the prompt. It is not lazy disk access. Catalog savings
depend on document size and directory organization. The unit test with 40 long
research notes verifies that its catalog uses less than 1% of the estimated
tokens required for all the documents; this is a synthetic test, not a model
benchmark or a universal savings claim.

Concept IDs are paths without `.md`. A source ID such as
`okf:research:findings/calibration` adds a caller-chosen bundle namespace.
`content_hash` identifies the exact document text, and `bundle.revision`
identifies the complete snapshot, including supporting files. Callers can use
these hashes to avoid reindexing unchanged knowledge. No hidden conversation
history or automatic cache is added.

### Budgeted discovery pages

An entry-count limit alone cannot bound prompt size when descriptions are long.
`OKFAdapter.adapt_catalog` fits complete, contiguous entries under `TokenBudget`,
counting the heading and continuation marker as well as the entries:

```python
from cemaf.ingestion import OKFAdapter
from cemaf.context.budget import TokenBudget

adapter = OKFAdapter(bundle_id="research", revision=bundle.revision)
page = await adapter.adapt_catalog(
    bundle, TokenBudget(max_tokens=300, reserved_for_output=0),
    directory="findings", offset=0,
)
print(page.source.content)
# Continue with offset=page.next_offset unless it is None.
```

The returned `OKFCatalogPage` carries a `ContextSource`, `next_offset`, and
`total_entries`. Each page retains the actual snapshot revision in its metadata.
Pinning the adapter's `revision` rejects pagination after the bundle changes;
restart discovery against that new snapshot. Pagination never silently skips an
entry that is too large. If the next entry cannot fit, increase the budget or pass
`include_descriptions=False`. Empty directories return a budget-checked heading.
Discovery and document reading each need their own per-call budget; when both
appear in one prompt, compile their sources under the combined budget.

### Compare sessions without reindexing everything

```python
previous = OKFBundle.load("/path/to/previous-snapshot")
current = OKFBundle.load("/path/to/current-snapshot")
changes = current.diff(previous)
changed_concepts = [current.get(key) for key in (*changes.added, *changes.modified)]
```

`OKFBundleDiff` reports sorted `added`, `modified`, and `removed` concept IDs,
separate `supporting_added`, `supporting_modified`, and `supporting_removed` paths,
and both snapshot revisions. Changes include metadata and formatting, since the
hash identifies exact source bytes. Renames appear as removal plus addition;
iteration order does not affect the result. `without_document(concept_id)` creates
a snapshot with a concept removed and raises `KeyError` for an unknown ID.

Applications can use these deltas with their existing retrieval store's add and
delete operations. The [two-session example](../examples/app_shapes/okf_project_memory.py)
reopens CEMAF's SQLite vector store, indexes only added/changed concepts, deletes
retired concepts, and preserves citations. Its integration test counts embedding
calls and verifies that an unchanged procedure is embedded only once across both
sessions. Unchanged stored documents retain their original indexing revision;
their content hashes still match the current bundle. Do not label an unchanged
stored record with a new revision unless that revision has actually been checked.

A diff reports direct file changes, not dependency invalidation. Changing a
supporting computation or protocol may require reevaluating linked findings even
when their text is unchanged. Existing graph relationships and application policy
own that decision. Diffs neither synchronize graph backends nor approve proposals.

## Compile context and retain evidence

```python
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.ingestion import create_adapter

budget = TokenBudget(max_tokens=2400, reserved_for_output=400)
estimator = SimpleTokenEstimator()
adapter = create_adapter(
    "okf", bundle_id="research", revision=bundle.revision,
    token_estimator=estimator,
)

# Inside an async function:
source = await adapter.adapt(concept, budget, priority=10)
compiled = await PriorityContextCompiler(estimator).compile(
    artifacts=((source.key, source.content),), memories=(), budget=budget,
)
```

`OKFAdapter` implements `ContextAdapter`. It preserves the complete concept and
raises `ValueError` if that concept exceeds the available budget. It never
truncates evidence or metadata. The normal compiler selects among supplied
artifacts under the combined budget. The default estimator is approximate;
inject a model-specific `TokenEstimator` when exact counts are required.

The adapter's `ContextSource.metadata` includes the original frontmatter, concept
path, bundle revision, document hash, and derived trust tier. The compiler's
artifact-pair API retains the source ID and text, but does not carry this metadata
dictionary forward. Keep the source metadata with the retrieval/citation record.
`concept.to_document(bundle_id=..., revision=...)` creates a normal retrieval
`Document`; `CitationTracker` preserves its metadata in the resulting citation.

## Use the existing knowledge graph

```python
from cemaf.knowledge import create_knowledge_graph, import_okf_bundle
from cemaf.memory.factories import create_memory_manager
from cemaf.orchestration.services import RuntimeServices

graph = create_knowledge_graph(create_memory_manager())
report = await import_okf_bundle(bundle, graph=graph, bundle_id="research")
services = RuntimeServices(knowledge_graph=graph)
```

Pass the services to `create_executor(agent_registry=..., services=services)`.
Agents receive the graph through `AgentContext.knowledge_graph`.

Each concept maps to `EntityType.CONCEPT`; its unrestricted original type remains
in `properties["okf_type"]`. CommonMark links become `RelationType.REFERENCES`,
without inferring a stronger relationship from prose. Local `sources[].resource`
references become `EXTRACTED_FROM`. Both root-relative and document-relative links
are supported. Broken targets are listed in `report.unresolved_links`, and their
original links remain in the document. External resources are never fetched.

Import uses the public `KnowledgeGraph` protocol. It requires unused concept IDs
and refuses to overwrite existing entities. Use a fresh graph, a backend-owned
branch, or a new bundle namespace for another snapshot. Import is not a graph
transaction or an incremental synchronization service; a backend failure can
leave partial writes. Backend transactions and branch merges remain backend-owned.

## Propose changes for human review

```python
proposal = concept.propose(
    body=concept.body + "\nA proposed clarification.\n",
    actor="cemaf/researcher",
    run_id="research-run-42",
)
bundle.with_document(proposal).write("/tmp/research-proposal")
```

The proposal retains extension metadata, removes prior `verified` claims, sets
`status: draft`, and records the generating actor, timestamp, CEMAF run ID, and
base document hash. An ordinary Git diff or pull request can then carry the
proposal through the project's human review process. Reviewers should check the
base hash before applying a proposal against a changed knowledge base.

Use `proposal.proposal_matches(current_concept)` for this check. It returns False
for changed source bytes, a different concept path, or missing proposal evidence.
This detects a stale proposal before review; it is not authentication, approval,
or an atomic compare-and-swap operation. The actual merge must still use the
review system's concurrency controls.

Export requires a new destination outside the loaded source bundle. It preserves
unchanged documents byte-for-byte, including YAML comments, index/log files, and
supporting assets. Edited frontmatter is reserialized with all parsed fields;
comments in an edited header are not retained. Export never approves or merges a
proposal. Human ratification and conflict resolution belong to the consuming
application's review workflow.

## Trust and compatibility boundaries

- `type` must be a non-empty string. Unknown types and additional metadata are
  accepted. Optional trust/provenance/computation fields are retained.
- `verified` accepts a mapping or list. The derived tiers are `unverified`,
  `machine-confirmed`, and `human-reviewed`. These are claims in the document,
  not authenticated identity, access control, or proof that an answer is correct.
- `is_stale(now=...)` uses `stale_after` with an explicit UTC offset. Missing or
  malformed optional timestamps do not exclude a concept. Applications decide
  how to use freshness, lifecycle, and trust signals.
- Reserved `index.md` and `log.md` files are preserved separately from concepts.
  Version declarations are retained even when unfamiliar. This adapter validates
  concept structure; it does not certify all optional conventions or log formats.
- Attested Computation metadata and supporting code are preserved as data.
  Loading an OKF bundle does not execute computations, attesters, `AGENTS.md`, or
  `SKILL.md`. Execution requires explicitly registered application tools/skills
  and the existing DAG/evaluation services.
- The loader ignores `.git` internals and rejects bundle symlinks. Escaping link
  targets remain opaque; import never follows them outside the bundle.

## Runnable proof and composition notes

### CEMAF describing itself

Architecture, modules, protocols, skills, agents, capabilities, and governance
descriptions use the same OKF representation as research knowledge:

```bash
uv run cemaf docs export-okf --output build/cemaf-okf
```

The destination must be new. Use `--repo-root /path/to/cemaf` when running outside
the checkout. The command exports repository documentation, statically discovered
Python modules and contracts, and an offline self-hosting registry snapshot.
It does not enumerate production identities or connect to external services.
The generated root index points to vocabulary and concept categories. Large
categories have file-based pages of at most 40 concepts, so ordinary Markdown
readers can navigate progressively without loading the whole export.

| Surface | Existing contract or adapter | What goes into OKF |
|---|---|---|
| Architecture, patterns, module guides, specifications | `MarkdownDocSource` / `DocSource` | One concept per documentation entry, with its original ID |
| Source modules, structural protocols, declared agents/skills/tools | `PythonContractDocSource` / `DocSource` | Static docstrings, public signatures, module links; source code is parsed without import or execution |
| Registered agents, tools, skills, selector capabilities | `RuntimeDocSource` | Public descriptions, goal schemas, tool safety metadata, capability candidates, skill/tool relationships |
| RBAC roles, identities, scoped grants, ABAC conditions | `GovernanceDocSource` / `MappingProvider` | Explicitly selected policy descriptions, never executable grants |
| Authorized disclosure | `GovernedDocSource` / `ScopeAuthorizer` | All-or-nothing export after checking every entry against trusted scope bindings |
| Agent-readable lookup after import | `OKFDocSource` / `DocIndex` | Existing docs search/retrieval tools and docs MCP can read the bundle |
| Meta-agent execution | `create_meta_executor`, `MetaServices`, `RuntimeServices` | Existing knowledge graph import makes concepts available to meta-agents |

`build_okf_bundle(sources=...)` accepts any structural `DocSource`; custom
applications need no inheritance. `metadata["okf_type"]` can provide a domain
type, and `metadata["related_ids"]` names other documentation entries. Duplicate
IDs fail rather than silently replacing evidence. Runtime exports describe public
interfaces and never serialize dependency objects or execute a skill. Static
declarations and actual runtime registrations are labeled separately.
Known relative links between exported Markdown guides also become portable
related-concept links. Original prose remains intact, so links to unexported
repository assets may still be unresolved in the bundle.

```python
from cemaf.docs_api import DocIndex, OKFDocSource, build_okf_bundle
from cemaf.meta.okf import RuntimeDocSource

bundle = build_okf_bundle(sources=(
    RuntimeDocSource(agent_registry=agents, tool_registry=tools, skill_registry=skills),
))
index = DocIndex()
index.add_from(sources=(OKFDocSource(bundle=bundle, bundle_id="project"),))
```

Compose those registries through `create_meta_executor` first when the snapshot
should include registered meta-agents. Pass `index` to the existing
`CemafDocsSearchTool`, `DocsRetrievalTool`, or docs MCP factory. Registry snapshots
are descriptive: loading them does not instantiate agents, register tools, grant
permissions, or activate instructions.

### RBAC, ABAC, and governance remain enforced by protocols

`ScopeAuthorizer` is a runtime-checkable structural interface implemented by
`RBACEnforcer`. An alternative policy implementation can supply the same `can`
method. `GovernedDocSource` receives a principal and a caller-owned mapping from
entry IDs to `(MemoryScope, scope_path)`; an entry cannot set its own scope through
frontmatter. Missing bindings or a denied check abort the whole source. Every load
checks current policy, so a provider's revocation is observed on the next export.

```python
from cemaf.security.okf import GovernedDocSource, GovernanceDocSource
from cemaf.security.rbac import RBACEnforcer

source = GovernanceDocSource(provider=mappings, principal_ids=("curator",))
governed = GovernedDocSource(
    source=source, authorizer=RBACEnforcer(mappings),
    principal_id="curator", bindings=trusted_scope_bindings,
)
bundle = build_okf_bundle(sources=(governed,))
```

The wrapper preserves the existing enforcer's semantics: role permissions may
grant access independently of direct ABAC grants. ABAC examples use scoped direct
grants without a broader role that would already allow the action. An exported
policy is knowledge about policy, not a new enforcement authority. Importing a
policy description never mutates `MappingProvider` or authorizes a principal.

An authorized export creates ordinary plaintext files. Runtime revocation cannot
recall an already exported copy. Destination permissions, recipient authorization,
and the review/merge workflow remain application responsibilities. This adapter
checks source disclosure with the existing `read` action; it does not define a
separate sharing policy or a transactional policy snapshot.

### Format versions, vocabulary versions, and Git history

OKF v0.2 deliberately leaves type taxonomies open. It does not define a central
ontology registry, ontology inference, or schema migrations. CEMAF therefore
exports a local application vocabulary as `ontology/cemaf.md`, with definitions
for modules, protocols, skills, capabilities, policies, and related concepts.
Unknown application types remain valid.

Keep three different versions explicit:

1. `okf_version: "0.2"` in the root index identifies the file-format version.
2. `cemaf_profile: {id: cemaf, version: "1.0", resource: /ontology/cemaf.md}`
   on exported concepts identifies CEMAF's vocabulary convention. This extension
   is CEMAF-defined, not an upstream OKF standard.
3. Git commits/tags track reviewed content history; `bundle.revision` pins the
   exact exported bytes independently of Git.

The vocabulary itself can be edited and reviewed in Git like any other concept.
Changing a type's meaning is a profile-version decision; changing a concept's
content is a knowledge-revision decision. No new version-control or ontology
runtime is introduced.

### Verification examples

```bash
uv run python examples/app_shapes/okf_research.py
uv run python examples/app_shapes/okf_research.py --proposal-dir /tmp/research-proposal
uv run python examples/app_shapes/okf_project_memory.py
uv run python examples/app_shapes/okf_self_hosting.py
uv run pytest tests/unit/knowledge/test_okf.py tests/unit/knowledge/test_okf_memory.py tests/integration/test_okf.py -q
```

The [offline example](../examples/app_shapes/okf_research.py) uses a checked-in
[research bundle](../examples/data/okf_research/index.md), `create_executor`,
`RuntimeServices`, the existing graph, context compiler, citation tracker,
`GroundednessEvaluator`, `GateEvalInterceptor`, events, and run logger. It extracts
a cited sentence, verifies the source revision, and exports a draft only after
the gate passes. The grounding check measures text overlap, not scientific truth.

The implementation extends `knowledge` for format I/O and graph projection and
`ingestion` for `ContextAdapter`. It reuses `KnowledgeGraph`, retrieval `Document`,
and `TokenEstimator`, following the existing RAG and composition-root examples.
The missing reusable behavior was the OKF format adapter; the example's research
agent and evidence evaluator are domain code. The
[integration tests](../tests/integration/test_okf.py) prove the graph, retrieval,
budget, citation, DAG gate, run provenance, and proposed-export path together.
They also cover persisted sessions, selective embedding, import-conflict preflight,
and rejection of empty, malformed, forged, or unsupported research reports. The
budgeted catalog adapter reuses `TokenBudget` and `TokenEstimator`; portable file
diffs extend the existing OKF snapshot model without adding a separate memory or
synchronization runtime.

The [self-hosting example](../examples/app_shapes/okf_self_hosting.py) exports
registered capabilities, static security contracts, and an authorized ABAC policy
description, reloads them through docs tools, and runs `MetaKnowledgeGraph` in a
real DAG against the imported concepts. The
[self-hosting integration tests](../tests/integration/test_okf_self_hosting.py)
also exercise full-framework CLI export, source/runtime distinction, and absence
of private dependency state in the exported bundle.
