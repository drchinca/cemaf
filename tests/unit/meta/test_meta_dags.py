"""Unit tests for pre-built DAG factory functions."""

from __future__ import annotations

from cemaf.core.enums import NodeType
from cemaf.meta.dags import (
    create_feature_synthesis_dag,
    create_knowledge_refresh_dag,
    create_self_audit_dag,
)


class TestCreateSelfAuditDag:
    """Tests for the self-audit DAG factory."""

    def test_returns_valid_dag(self) -> None:
        """DAG passes structural validation."""
        dag = create_self_audit_dag()
        assert dag.validate_structure() is True

    def test_dag_name(self) -> None:
        """DAG has expected name."""
        dag = create_self_audit_dag()
        assert dag.name == "self_audit"

    def test_has_audit_node(self) -> None:
        """DAG contains exactly one agent node referencing MetaAuditor."""
        dag = create_self_audit_dag()
        assert len(dag.nodes) == 1
        node = dag.nodes[0]
        assert node.type == NodeType.AGENT
        assert node.ref_id == "MetaAuditor"
        assert node.output_key == "audit_report"

    def test_no_edges(self) -> None:
        """Single-node DAG has no edges."""
        dag = create_self_audit_dag()
        assert len(dag.edges) == 0


class TestCreateFeatureSynthesisDag:
    """Tests for the feature synthesis DAG factory."""

    def test_returns_valid_dag(self) -> None:
        """DAG passes structural validation."""
        dag = create_feature_synthesis_dag()
        assert dag.validate_structure() is True

    def test_dag_name(self) -> None:
        """DAG has expected name."""
        dag = create_feature_synthesis_dag()
        assert dag.name == "feature_synthesis"

    def test_has_two_nodes(self) -> None:
        """DAG contains architect and synthesizer nodes."""
        dag = create_feature_synthesis_dag()
        assert len(dag.nodes) == 2
        ref_ids = {n.ref_id for n in dag.nodes}
        assert ref_ids == {"MetaArchitect", "MetaSynthesizer"}

    def test_has_one_edge(self) -> None:
        """DAG has exactly one edge from architect to synthesizer."""
        dag = create_feature_synthesis_dag()
        assert len(dag.edges) == 1
        edge = dag.edges[0]
        assert str(edge.source) == "architect"
        assert str(edge.target) == "synthesize"

    def test_node_output_keys(self) -> None:
        """Each node has the correct output key."""
        dag = create_feature_synthesis_dag()
        node_map = {str(n.id): n for n in dag.nodes}
        assert node_map["architect"].output_key == "dag_spec"
        assert node_map["synthesize"].output_key == "agent_code"


class TestCreateKnowledgeRefreshDag:
    """Tests for the knowledge refresh DAG factory."""

    def test_returns_valid_dag(self) -> None:
        """DAG passes structural validation."""
        dag = create_knowledge_refresh_dag()
        assert dag.validate_structure() is True

    def test_dag_name(self) -> None:
        """DAG has expected name."""
        dag = create_knowledge_refresh_dag()
        assert dag.name == "knowledge_refresh"

    def test_has_two_nodes(self) -> None:
        """DAG contains audit and KG nodes."""
        dag = create_knowledge_refresh_dag()
        assert len(dag.nodes) == 2
        ref_ids = {n.ref_id for n in dag.nodes}
        assert ref_ids == {"MetaAuditor", "MetaKnowledgeGraph"}

    def test_has_one_edge(self) -> None:
        """DAG has exactly one edge from audit to KG update."""
        dag = create_knowledge_refresh_dag()
        assert len(dag.edges) == 1
        edge = dag.edges[0]
        assert str(edge.source) == "audit"
        assert str(edge.target) == "update_kg"

    def test_node_output_keys(self) -> None:
        """Each node has the correct output key."""
        dag = create_knowledge_refresh_dag()
        node_map = {str(n.id): n for n in dag.nodes}
        assert node_map["audit"].output_key == "audit_data"
        assert node_map["update_kg"].output_key == "kg_result"
