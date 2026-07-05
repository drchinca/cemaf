"""Pre-built DAG factory functions for common self-hosting workflows."""

from __future__ import annotations

from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Edge, Node


def create_dream_dag() -> DAG:
    """DAG that runs DreamAgent for autonomous memory consolidation."""
    dag = DAG(name="dream", description="Autonomous memory consolidation cycle")
    dag = dag.add_node(
        node=Node.agent(
            id="dream",
            name="Dream Agent",
            agent_id="MetaDream",
            output_key="dream_result",
        )
    )
    return dag


def create_self_audit_dag() -> DAG:
    """DAG that runs AuditAgent to inspect recent execution history."""
    dag = DAG(name="self_audit", description="Audit recent CEMAF execution")
    dag = dag.add_node(
        node=Node.agent(
            id="audit",
            name="Audit Agent",
            agent_id="MetaAuditor",
            output_key="audit_report",
        )
    )
    return dag


def create_feature_synthesis_dag() -> DAG:
    """DAG: Architect designs a pipeline, then Synthesizer generates the agent code."""
    dag = DAG(name="feature_synthesis", description="Generate a new agent from feature spec")
    dag = dag.add_node(
        node=Node.agent(
            id="architect",
            name="Architect",
            agent_id="MetaArchitect",
            output_key="dag_spec",
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="synthesize",
            name="Synthesizer",
            agent_id="MetaSynthesizer",
            output_key="agent_code",
        )
    )
    dag = dag.add_edge(edge=Edge(source=NodeID("architect"), target=NodeID("synthesize")))
    return dag


def create_context_compaction_dag() -> DAG:
    """DAG: Audit stale context, then compact via summary generation."""
    dag = DAG(name="context_compaction", description="Audit and compact stale context sources")
    dag = dag.add_node(
        node=Node.agent(
            id="audit_context",
            name="Audit Context",
            agent_id="MetaAuditor",
            input_mapping={"analysis_type": "quality"},
            output_key="audit_data",
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="update_kg",
            name="KG Refresh",
            agent_id="MetaKnowledgeGraph",
            input_mapping={"operation": "refresh"},
            output_key="kg_result",
        )
    )
    dag = dag.add_edge(edge=Edge(source=NodeID("audit_context"), target=NodeID("update_kg")))
    return dag


def create_solution_engine_dag() -> DAG:
    """Full self-hosting loop: diagnose → design → version → learn.

    Uses checkpoints between phases for quality gating.
    This is CEMAF solving problems by using its own primitives.
    """
    dag = DAG(name="solution_engine", description="Autonomous multi-agent solution designer")

    # Phase 1: DIAGNOSE — audit existing state
    dag = dag.add_node(
        node=Node.agent(
            id="diagnose",
            name="Diagnose",
            agent_id="MetaAuditor",
            input_mapping={"analysis_type": "full"},
            output_key="diagnosis",
        )
    )

    # Checkpoint: verify diagnosis quality before designing
    dag = dag.add_node(node=Node.checkpoint(id="cp_diagnosis", name="Diagnosis Gate"))

    # Phase 2: DESIGN — solution designer creates versioned architecture
    dag = dag.add_node(
        node=Node.agent(
            id="design",
            name="Design Solution",
            agent_id="MetaSolutionDesigner",
            output_key="solution",
        )
    )

    # Checkpoint: verify design quality before learning
    dag = dag.add_node(node=Node.checkpoint(id="cp_design", name="Design Gate"))

    # Phase 3: LEARN — consolidate into memory
    dag = dag.add_node(
        node=Node.agent(
            id="learn",
            name="Knowledge Update",
            agent_id="MetaKnowledgeGraph",
            input_mapping={"operation": "refresh"},
            output_key="kg_update",
        )
    )

    # Wire the chain
    dag = dag.add_edge(edge=Edge(source=NodeID("diagnose"), target=NodeID("cp_diagnosis")))
    dag = dag.add_edge(edge=Edge(source=NodeID("cp_diagnosis"), target=NodeID("design")))
    dag = dag.add_edge(edge=Edge(source=NodeID("design"), target=NodeID("cp_design")))
    dag = dag.add_edge(edge=Edge(source=NodeID("cp_design"), target=NodeID("learn")))

    return dag


def create_app_synthesis_dag() -> DAG:
    """DAG: MetaSpecifier → MetaArchitect → MetaSynthesizer → MetaScaffolder.

    Initial context supplies the feature/app synthesis inputs:
    feature_description, change_id, capabilities, project_name, target_dir,
    and agent_name. Optional keys: constraints, goal_fields, result_fields,
    cemaf_source, overwrite.
    """
    dag = DAG(
        name="app_synthesis",
        description="Synthesize a runnable CEMAF-based app from a feature description",
    )
    dag = dag.add_node(
        node=Node.agent(
            id="specify",
            name="Specifier",
            agent_id="MetaSpecifier",
            input_mapping={
                "feature_description": "$$feature_description$$",
                "change_id": "$$change_id$$",
                "capabilities": "$$capabilities$$",
                "constraints": "$$constraints$$",
            },
            output_key="spec_result",
            structured_output=True,
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="design",
            name="Architect",
            agent_id="MetaArchitect",
            input_mapping={
                "feature_description": "$$feature_description$$",
                "constraints": "$$constraints$$",
            },
            output_key="dag_spec",
            structured_output=True,
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="synthesize",
            name="Synthesizer",
            agent_id="MetaSynthesizer",
            input_mapping={
                "agent_name": "$$agent_name$$",
                "description": "$$feature_description$$",
                "goal_fields": "$$goal_fields$$",
                "result_fields": "$$result_fields$$",
            },
            output_key="agent_code",
            structured_output=True,
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="scaffold",
            name="Scaffolder",
            agent_id="MetaScaffolder",
            input_mapping={
                "proposal": "$$spec_result.proposal$$",
                "project_name": "$$project_name$$",
                "target_dir": "$$target_dir$$",
                "generated_agents": [
                    {
                        "class_name": "$$agent_name$$Agent",
                        "goal_class_name": "$$agent_name$$Goal",
                        "source": "$$agent_code.agent_code$$",
                    }
                ],
                "cemaf_source": "$$cemaf_source$$",
                "overwrite": "$$overwrite$$",
            },
            output_key="scaffold_result",
            structured_output=True,
        )
    )
    dag = dag.add_edge(edge=Edge(source=NodeID("specify"), target=NodeID("design")))
    dag = dag.add_edge(edge=Edge(source=NodeID("design"), target=NodeID("synthesize")))
    dag = dag.add_edge(edge=Edge(source=NodeID("synthesize"), target=NodeID("scaffold")))
    return dag


def create_self_spec_dag() -> DAG:
    """DAG: MetaSpecifier authors + validates a proposal, MetaAuditor records outcome.

    Closes the self-spec loop: feature description in, audit entry out.
    """
    dag = DAG(name="self_spec", description="Author, validate, and audit an OpenSpec proposal")
    dag = dag.add_node(
        node=Node.agent(
            id="specify",
            name="Specifier",
            agent_id="MetaSpecifier",
            output_key="spec_result",
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="audit_spec",
            name="Audit Spec",
            agent_id="MetaAuditor",
            input_mapping={"analysis_type": "quality"},
            output_key="audit_report",
        )
    )
    dag = dag.add_edge(edge=Edge(source=NodeID("specify"), target=NodeID("audit_spec")))
    return dag


def create_knowledge_refresh_dag() -> DAG:
    """DAG: Audit recent runs then update knowledge graph."""
    dag = DAG(name="knowledge_refresh", description="Refresh CEMAF knowledge graph from execution history")
    dag = dag.add_node(
        node=Node.agent(
            id="audit",
            name="Audit Agent",
            agent_id="MetaAuditor",
            output_key="audit_data",
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="update_kg",
            name="KG Agent",
            agent_id="MetaKnowledgeGraph",
            input_mapping={"operation": "refresh"},
            output_key="kg_result",
        )
    )
    dag = dag.add_edge(edge=Edge(source=NodeID("audit"), target=NodeID("update_kg")))
    return dag
