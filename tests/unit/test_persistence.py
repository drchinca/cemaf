"""Tests for persistence entities, protocols, and factories."""

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
from cemaf.persistence.protocols import (
    ArtifactStore,
    ContentStore,
    ProjectStore,
    RunStore,
)


class TestProject:
    def test_create_with_defaults(self):
        project = Project(name="test")
        assert project.name == "test"
        assert project.status == ProjectStatus.DRAFT
        assert project.id.startswith("proj_")
        assert project.description == ""
        assert project.metadata == {}

    def test_create_with_all_fields(self):
        project = Project(
            id=ProjectID("proj_123"),
            name="my project",
            description="desc",
            status=ProjectStatus.ACTIVE,
            tenant_id="t1",
            owner_id="o1",
            metadata={"key": "val"},
        )
        assert project.id == "proj_123"
        assert project.tenant_id == "t1"

    def test_frozen(self):
        project = Project(name="test")
        with pytest.raises(Exception):
            project.name = "changed"  # type: ignore[misc]

    def test_with_status(self):
        project = Project(name="test", status=ProjectStatus.DRAFT)
        updated = project.with_status(status=ProjectStatus.ACTIVE)
        assert updated.status == ProjectStatus.ACTIVE
        assert project.status == ProjectStatus.DRAFT  # original unchanged
        assert updated.name == "test"


class TestContextArtifact:
    def test_create_with_defaults(self):
        artifact = ContextArtifact(
            project_id=ProjectID("proj_1"),
            type=ContextArtifactType.BRAND_CONSTITUTION,
            content="hello",
        )
        assert artifact.id.startswith("art_")
        assert artifact.version == 1
        assert artifact.content == "hello"

    def test_with_new_version(self):
        artifact = ContextArtifact(
            project_id=ProjectID("proj_1"),
            type=ContextArtifactType.BRAND_CONSTITUTION,
            content="v1",
            version=1,
        )
        v2 = artifact.with_new_version(content="v2", sha="abc123")
        assert v2.version == 2
        assert v2.content == "v2"
        assert v2.sha == "abc123"
        assert v2.id != artifact.id  # New ID
        assert artifact.content == "v1"  # Original unchanged


class TestContentItem:
    def test_create_with_defaults(self):
        item = ContentItem(
            project_id=ProjectID("proj_1"),
            platform="instagram",
            format="post",
            brief="Write about AI",
        )
        assert item.id.startswith("cnt_")
        assert item.status == ContentStatus.DRAFT
        assert item.hashtags == ()

    def test_with_status(self):
        item = ContentItem(
            project_id=ProjectID("proj_1"),
            platform="twitter",
            format="thread",
            brief="Thread about ML",
        )
        updated = item.with_status(status=ContentStatus.APPROVED)
        assert updated.status == ContentStatus.APPROVED
        assert item.status == ContentStatus.DRAFT


class TestRun:
    def test_create_with_defaults(self):
        run = Run(
            project_id=ProjectID("proj_1"),
            pipeline="research",
        )
        assert run.id.startswith("run_")
        assert run.status == RunStatus.PENDING
        assert run.total_tokens_used == 0
        assert run.total_cost_usd == 0.0

    def test_duration_none_when_not_completed(self):
        run = Run(project_id=ProjectID("proj_1"), pipeline="test")
        assert run.duration_seconds is None

    def test_with_completion(self):
        run = Run(project_id=ProjectID("proj_1"), pipeline="test")
        completed = run.with_completion(
            status=RunStatus.COMPLETED,
            outputs={"result": "done"},
            error=None,
        )
        assert completed.status == RunStatus.COMPLETED
        assert completed.outputs == {"result": "done"}
        assert completed.completed_at is not None
        assert completed.duration_seconds is not None
        assert run.status == RunStatus.PENDING  # Original unchanged

    def test_with_completion_error(self):
        run = Run(project_id=ProjectID("proj_1"), pipeline="test")
        failed = run.with_completion(
            status=RunStatus.FAILED,
            outputs={},
            error="Something broke",
        )
        assert failed.status == RunStatus.FAILED
        assert failed.error == "Something broke"


class TestProtocolCompliance:
    """Verify that protocol isinstance checks work."""

    def test_project_store_protocol(self):
        class MyProjectStore:
            async def create(self, project):
                return project

            async def get(self, project_id):
                return None

            async def update(self, project):
                return project

            async def delete(self, project_id):
                return True

            async def list_by_status(self, status=None, limit=100):
                return ()

        assert isinstance(MyProjectStore(), ProjectStore)

    def test_artifact_store_protocol(self):
        class MyArtifactStore:
            async def create(self, artifact):
                return artifact

            async def get(self, artifact_id):
                return None

            async def get_latest(self, project_id, artifact_type):
                return None

            async def list_by_project(self, project_id, artifact_type=None):
                return ()

            async def list_versions(self, project_id, artifact_type):
                return ()

        assert isinstance(MyArtifactStore(), ArtifactStore)

    def test_content_store_protocol(self):
        class MyContentStore:
            async def create(self, content):
                return content

            async def get(self, content_id):
                return None

            async def update(self, content):
                return content

            async def list_by_project(self, project_id, status=None, platform=None, limit=100):
                return ()

            async def list_scheduled(self, limit=100):
                return ()

        assert isinstance(MyContentStore(), ContentStore)

    def test_run_store_protocol(self):
        class MyRunStore:
            async def create(self, run):
                return run

            async def get(self, run_id):
                return None

            async def update(self, run):
                return run

            async def list_by_project(self, project_id, status=None, limit=100):
                return ()

            async def get_latest(self, project_id):
                return None

        assert isinstance(MyRunStore(), RunStore)


class TestFactories:
    def test_project_store_factory_unknown_backend(self):
        from cemaf.persistence.factories import create_project_store_from_config

        with pytest.raises(ValueError, match="Unsupported project store backend"):
            create_project_store_from_config()

    def test_artifact_store_factory_unknown_backend(self):
        from cemaf.persistence.factories import create_artifact_store_from_config

        with pytest.raises(ValueError, match="Unsupported artifact store backend"):
            create_artifact_store_from_config()

    def test_content_store_factory_unknown_backend(self):
        from cemaf.persistence.factories import create_content_store_from_config

        with pytest.raises(ValueError, match="Unsupported content store backend"):
            create_content_store_from_config()

    def test_run_store_factory_unknown_backend(self):
        from cemaf.persistence.factories import create_run_store_from_config

        with pytest.raises(ValueError, match="Unsupported run store backend"):
            create_run_store_from_config()


class TestEnums:
    def test_project_status_values(self):
        assert ProjectStatus.DRAFT.value == "draft"
        assert ProjectStatus.ACTIVE.value == "active"
        assert ProjectStatus.ARCHIVED.value == "archived"

    def test_content_status_values(self):
        assert ContentStatus.DRAFT.value == "draft"
        assert ContentStatus.PUBLISHED.value == "published"
        assert ContentStatus.SCHEDULED.value == "scheduled"
