"""Pre-built DAG factory functions for common self-hosting workflows."""

from __future__ import annotations

from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Edge, Node


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
