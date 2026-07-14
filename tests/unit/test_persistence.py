"""Tests for persistence entities, protocols, and factories."""

import pytest

from cemaf.config.protocols import Settings
from cemaf.core.enums import RunStatus
from cemaf.core.types import ProjectID
from cemaf.persistence.entities import (
    ContentItem,
    ContentStatus,
    ContextArtifact,
    Project,
    ProjectStatus,
    Run,
)
from cemaf.persistence.factories import (
    artifact_store_registry,
    content_store_registry,
    create_artifact_store,
    create_artifact_store_from_config,
    create_content_store,
    create_content_store_from_config,
    create_project_store,
    create_project_store_from_config,
    create_run_store,
    create_run_store_from_config,
    project_store_registry,
    run_store_registry,
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
            type="brand_constitution",
            content="hello",
        )
        assert artifact.id.startswith("art_")
        assert artifact.version == 1
        assert artifact.content == "hello"

    def test_with_new_version(self):
        artifact = ContextArtifact(
            project_id=ProjectID("proj_1"),
            type="brand_constitution",
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
    def test_project_store_factory_requires_registered_backend(self):
        with pytest.raises(ValueError, match="No project_store backend configured"):
            create_project_store_from_config()

    def test_artifact_store_factory_requires_registered_backend(self):
        with pytest.raises(ValueError, match="No artifact_store backend configured"):
            create_artifact_store_from_config()

    def test_content_store_factory_requires_registered_backend(self):
        with pytest.raises(ValueError, match="No content_store backend configured"):
            create_content_store_from_config()

    def test_run_store_factory_requires_registered_backend(self):
        with pytest.raises(ValueError, match="No run_store backend configured"):
            create_run_store_from_config()

    def test_register_custom_project_store_backend(self):
        class MyProjectStore:
            pass

        store = MyProjectStore()
        project_store_registry.register(backend="unit-project", factory=lambda **_: store)

        assert create_project_store(backend="unit-project") is store

    def test_register_custom_artifact_store_backend(self):
        class MyArtifactStore:
            pass

        store = MyArtifactStore()
        artifact_store_registry.register(backend="unit-artifact", factory=lambda **_: store)

        assert create_artifact_store(backend="unit-artifact") is store

    def test_register_custom_content_store_backend(self):
        class MyContentStore:
            pass

        store = MyContentStore()
        content_store_registry.register(backend="unit-content", factory=lambda **_: store)

        assert create_content_store(backend="unit-content") is store

    def test_register_custom_run_store_backend(self):
        class MyRunStore:
            pass

        store = MyRunStore()
        run_store_registry.register(backend="unit-run", factory=lambda **_: store)

        assert create_run_store(backend="unit-run") is store

    def test_create_registered_project_store_from_env(self, monkeypatch):
        captured = {}

        class MyProjectStore:
            pass

        def factory(**kwargs):
            captured.update(kwargs)
            return MyProjectStore()

        project_store_registry.register(backend="env-project", factory=factory)
        monkeypatch.setenv("CEMAF_PERSISTENCE_PROJECT_STORE_BACKEND", "env-project")
        monkeypatch.setenv("DATABASE_URL", "postgresql://example/project")

        store = create_project_store_from_config()

        assert isinstance(store, MyProjectStore)
        assert captured["database_url"] == "postgresql://example/project"

    def test_project_store_from_config_uses_settings_app_name_defaults(self, monkeypatch):
        captured = {}

        class MyProjectStore:
            pass

        def factory(**kwargs):
            captured.update(kwargs)
            return MyProjectStore()

        project_store_registry.register(backend="settings-project", factory=factory)
        monkeypatch.setenv("CEMAF_PERSISTENCE_PROJECT_STORE_BACKEND", "settings-project")
        monkeypatch.delenv("MONGODB_DATABASE", raising=False)
        monkeypatch.delenv("DYNAMODB_PROJECTS_TABLE", raising=False)
        settings = Settings(app_name="context_app")

        store = create_project_store_from_config(settings=settings)

        assert isinstance(store, MyProjectStore)
        assert captured["mongodb_database"] == "context_app"
        assert captured["dynamodb_projects_table"] == "context_app_projects"

    def test_create_registered_artifact_store_from_env(self, monkeypatch):
        captured = {}

        class MyArtifactStore:
            pass

        def factory(**kwargs):
            captured.update(kwargs)
            return MyArtifactStore()

        artifact_store_registry.register(backend="env-artifact", factory=factory)
        monkeypatch.setenv("CEMAF_PERSISTENCE_ARTIFACT_STORE_BACKEND", "env-artifact")
        monkeypatch.setenv("S3_ARTIFACTS_BUCKET", "cemaf-artifacts")
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        store = create_artifact_store_from_config()

        assert isinstance(store, MyArtifactStore)
        assert captured["s3_artifacts_bucket"] == "cemaf-artifacts"
        assert captured["aws_region"] == "us-west-2"

    def test_create_registered_content_store_from_env(self, monkeypatch):
        captured = {}

        class MyContentStore:
            pass

        def factory(**kwargs):
            captured.update(kwargs)
            return MyContentStore()

        content_store_registry.register(backend="env-content", factory=factory)
        monkeypatch.setenv("CEMAF_PERSISTENCE_CONTENT_STORE_BACKEND", "env-content")
        monkeypatch.setenv("MONGODB_URI", "mongodb://example/content")

        store = create_content_store_from_config()

        assert isinstance(store, MyContentStore)
        assert captured["mongodb_uri"] == "mongodb://example/content"

    def test_create_registered_run_store_from_env(self, monkeypatch):
        captured = {}

        class MyRunStore:
            pass

        def factory(**kwargs):
            captured.update(kwargs)
            return MyRunStore()

        run_store_registry.register(backend="env-run", factory=factory)
        monkeypatch.setenv("CEMAF_PERSISTENCE_RUN_STORE_BACKEND", "env-run")
        monkeypatch.setenv("TIMESCALE_URL", "postgresql://example/runs")

        store = create_run_store_from_config()

        assert isinstance(store, MyRunStore)
        assert captured["timescale_url"] == "postgresql://example/runs"


class TestEnums:
    def test_project_status_values(self):
        assert ProjectStatus.DRAFT.value == "draft"
        assert ProjectStatus.ACTIVE.value == "active"
        assert ProjectStatus.ARCHIVED.value == "archived"

    def test_content_status_values(self):
        assert ContentStatus.DRAFT.value == "draft"
        assert ContentStatus.PUBLISHED.value == "published"
        assert ContentStatus.SCHEDULED.value == "scheduled"
