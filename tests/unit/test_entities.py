"""
Unit tests for core entities.

Tests:
- Project
- ContextArtifact
- ContentItem
- Run

Uses fixtures from conftest.py:
- sample_project: Pre-configured Project
- sample_artifact: Pre-configured ContextArtifact
- sample_run: Pre-configured Run
"""

import pytest

from cemaf.core.enums import ContextArtifactType, RunStatus
from cemaf.core.types import ProjectID
from cemaf.persistence.entities import (
    ContentItem,
    ContentStatus,
    ContextArtifact,
    Project,
    ProjectStatus,
    Run,
)


class TestProject:
    """Tests for Project entity."""

    def test_project_creation(self, sample_project: Project):
        """Project can be created."""
        assert sample_project.name == "Test Project"
        assert sample_project.status == ProjectStatus.DRAFT

    def test_project_with_status(self, sample_project: Project):
        """Project.with_status creates copy with new status."""
        active = sample_project.with_status(ProjectStatus.ACTIVE)

        # Original unchanged
        assert sample_project.status == ProjectStatus.DRAFT
        # New project has new status
        assert active.status == ProjectStatus.ACTIVE
        # ID preserved
        assert active.id == sample_project.id

    def test_project_is_immutable(self, sample_project: Project):
        """Project is frozen/immutable."""
        from pydantic import ValidationError

        with pytest.raises((TypeError, AttributeError, ValidationError)):
            sample_project.name = "New Name"  # type: ignore


class TestContextArtifact:
    """Tests for ContextArtifact entity."""

    def test_artifact_creation(self):
        """ContextArtifact can be created."""
        artifact = ContextArtifact(
            project_id=ProjectID("proj-1"),
            type=ContextArtifactType.BRAND_CONSTITUTION,
            content="Brand values...",
            version=1,
            sha="abc123",
        )

        assert artifact.type == ContextArtifactType.BRAND_CONSTITUTION
        assert artifact.version == 1

    def test_with_new_version(self):
        """with_new_version creates new version."""
        original = ContextArtifact(
            project_id=ProjectID("proj-1"),
            type=ContextArtifactType.GLOSSARY,
            content="Original content",
            version=1,
            sha="abc",
        )

        updated = original.with_new_version(
            content="Updated content",
            sha="def",
        )

        # Original unchanged
        assert original.version == 1
        assert original.content == "Original content"
        # New version incremented
        assert updated.version == 2
        assert updated.content == "Updated content"
        assert updated.sha == "def"
        # New ID generated
        assert updated.id != original.id


class TestContentItem:
    """Tests for ContentItem entity."""

    def test_content_creation(self):
        """ContentItem can be created."""
        content = ContentItem(
            project_id=ProjectID("proj-1"),
            platform="instagram",
            format="post",
            brief="Create engagement post",
            body="This is the content...",
        )

        assert content.platform == "instagram"
        assert content.status == ContentStatus.DRAFT

    def test_with_status(self):
        """ContentItem.with_status updates status."""
        content = ContentItem(
            project_id=ProjectID("proj-1"),
            platform="twitter",
            format="tweet",
            brief="Tweet about product",
        )

        scheduled = content.with_status(ContentStatus.SCHEDULED)

        assert content.status == ContentStatus.DRAFT
        assert scheduled.status == ContentStatus.SCHEDULED


class TestRun:
    """Tests for Run entity."""

    def test_run_creation(self):
        """Run can be created."""
        run = Run(
            project_id=ProjectID("proj-1"),
            pipeline="content_generation",
            inputs={"topic": "AI"},
        )

        assert run.pipeline == "content_generation"
        assert run.status == RunStatus.PENDING

    def test_with_completion(self):
        """Run.with_completion completes the run."""
        run = Run(
            project_id=ProjectID("proj-1"),
            pipeline="test",
            inputs={},
        )

        completed = run.with_completion(
            status=RunStatus.COMPLETED,
            outputs={"result": "success"},
        )

        assert run.status == RunStatus.PENDING
        assert completed.status == RunStatus.COMPLETED
        assert completed.outputs == {"result": "success"}
        assert completed.completed_at is not None

    def test_duration_seconds(self):
        """Run.duration_seconds calculates duration."""
        run = Run(
            project_id=ProjectID("proj-1"),
            pipeline="test",
            inputs={},
        )

        # Not completed yet
        assert run.duration_seconds is None

        # Complete it
        completed = run.with_completion(RunStatus.COMPLETED, {})

        # Should have duration now
        assert completed.duration_seconds is not None
        assert completed.duration_seconds >= 0
