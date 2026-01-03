"""
Tests for type-safe context paths.
"""

from cemaf.context.context import Context
from cemaf.context.paths import ContextPath, TypedContext, create_path_builder


class TestContextPath:
    """Tests for ContextPath."""

    def test_create_path(self):
        """Create a typed context path."""
        path = ContextPath[str]("user.name")

        assert path.path == "user.name"
        assert str(path) == "user.name"

    def test_path_with_description(self):
        """Create path with description."""
        path = ContextPath[int]("user.age", description="User's age in years")

        assert path.path == "user.age"
        assert path.description == "User's age in years"

    def test_path_repr(self):
        """Path representation."""
        path = ContextPath[str]("user.name")
        assert repr(path) == "ContextPath[user.name]"

        path_with_desc = ContextPath[str]("user.email", description="User email address")
        assert "User email address" in repr(path_with_desc)

    def test_path_equality(self):
        """Paths with same path string are equal."""
        path1 = ContextPath[str]("user.name")
        path2 = ContextPath[str]("user.name")
        path3 = ContextPath[int]("user.age")

        assert path1 == path2
        assert path1 != path3

    def test_path_hashable(self):
        """Paths are hashable."""
        path1 = ContextPath[str]("user.name")
        path2 = ContextPath[str]("user.email")

        paths_set = {path1, path2}
        assert len(paths_set) == 2
        assert path1 in paths_set

    def test_path_as_dict_key(self):
        """Paths can be used as dict keys."""
        path1 = ContextPath[str]("user.name")
        path2 = ContextPath[int]("user.age")

        mapping = {path1: "Alice", path2: 30}

        assert mapping[path1] == "Alice"
        assert mapping[path2] == 30


class TestTypedContext:
    """Tests for TypedContext."""

    def test_create_typed_context(self):
        """Create a typed context wrapper."""
        ctx = Context(data={"user": {"name": "Alice"}})
        typed_ctx = TypedContext(ctx)

        assert typed_ctx.unwrap() == ctx

    def test_get_with_typed_path(self):
        """Get value using typed path."""
        user_name = ContextPath[str]("user.name")

        ctx = TypedContext(Context(data={"user": {"name": "Alice"}}))
        name = ctx.get(user_name)

        assert name == "Alice"

    def test_get_with_string_path(self):
        """Get value using string path (backward compatible)."""
        ctx = TypedContext(Context(data={"user": {"age": 30}}))
        age = ctx.get("user.age")

        assert age == 30

    def test_get_with_default(self):
        """Get with default value."""
        user_email = ContextPath[str]("user.email")

        ctx = TypedContext(Context())
        email = ctx.get(user_email, "default@example.com")

        assert email == "default@example.com"

    def test_set_with_typed_path(self):
        """Set value using typed path."""
        user_name = ContextPath[str]("user.name")

        ctx = TypedContext(Context())
        new_ctx = ctx.set(user_name, "Bob")

        assert new_ctx.get(user_name) == "Bob"
        assert ctx.get(user_name) is None  # Original unchanged

    def test_set_with_string_path(self):
        """Set value using string path (backward compatible)."""
        ctx = TypedContext(Context())
        new_ctx = ctx.set("user.age", 25)

        assert new_ctx.get("user.age") == 25

    def test_set_nested_path(self):
        """Set value in nested path."""
        profile_bio = ContextPath[str]("user.profile.bio")

        ctx = TypedContext(Context())
        ctx = ctx.set(profile_bio, "Software engineer")

        assert ctx.get(profile_bio) == "Software engineer"
        assert ctx.get("user.profile.bio") == "Software engineer"

    def test_delete_with_typed_path(self):
        """Delete value using typed path."""
        user_name = ContextPath[str]("user.name")

        ctx = TypedContext(Context(data={"user": {"name": "Alice", "age": 30}}))
        new_ctx = ctx.delete(user_name)

        assert new_ctx.get(user_name) is None
        assert new_ctx.get("user.age") == 30  # Other fields preserved

    def test_delete_with_string_path(self):
        """Delete value using string path."""
        ctx = TypedContext(Context(data={"user": {"name": "Alice"}}))
        new_ctx = ctx.delete("user.name")

        assert new_ctx.get("user.name") is None

    def test_merge_typed_contexts(self):
        """Merge two typed contexts."""
        ctx1 = TypedContext(Context(data={"user": {"name": "Alice"}}))
        ctx2 = TypedContext(Context(data={"user": {"age": 30}}))

        merged = ctx1.merge(ctx2)

        assert merged.get("user.age") == 30

    def test_merge_with_raw_context(self):
        """Merge typed context with raw Context."""
        typed_ctx = TypedContext(Context(data={"a": 1}))
        raw_ctx = Context(data={"b": 2})

        merged = typed_ctx.merge(raw_ctx)

        assert merged.get("a") == 1
        assert merged.get("b") == 2

    def test_to_dict(self):
        """Convert to dictionary."""
        ctx = TypedContext(Context(data={"user": {"name": "Alice"}}))
        data = ctx.to_dict()

        assert data == {"user": {"name": "Alice"}}

    def test_from_dict(self):
        """Create from dictionary."""
        data = {"user": {"name": "Bob", "age": 25}}
        ctx = TypedContext.from_dict(data)

        assert ctx.get("user.name") == "Bob"
        assert ctx.get("user.age") == 25

    def test_typed_context_repr(self):
        """TypedContext representation."""
        ctx = TypedContext(Context(data={"test": "value"}))
        repr_str = repr(ctx)

        assert "TypedContext" in repr_str
        assert "test" in repr_str


class TestPathDefinitions:
    """Tests for defining path schemas."""

    def test_define_path_schema(self):
        """Define a schema of paths."""

        class UserPaths:
            name = ContextPath[str]("user.name")
            age = ContextPath[int]("user.age")
            email = ContextPath[str]("user.email")
            tags = ContextPath[list[str]]("user.tags")

        ctx = TypedContext(Context())
        ctx = ctx.set(UserPaths.name, "Alice")
        ctx = ctx.set(UserPaths.age, 30)
        ctx = ctx.set(UserPaths.email, "alice@example.com")
        ctx = ctx.set(UserPaths.tags, ["python", "ai"])

        assert ctx.get(UserPaths.name) == "Alice"
        assert ctx.get(UserPaths.age) == 30
        assert ctx.get(UserPaths.email) == "alice@example.com"
        assert ctx.get(UserPaths.tags) == ["python", "ai"]

    def test_nested_path_schema(self):
        """Define nested path schemas."""

        class Paths:
            # User paths
            user_name = ContextPath[str]("user.name")
            user_profile_bio = ContextPath[str]("user.profile.bio")

            # Tool paths
            search_results = ContextPath[list]("tools.search.results")
            search_query = ContextPath[str]("tools.search.query")

        ctx = TypedContext(Context())
        ctx = ctx.set(Paths.user_name, "Bob")
        ctx = ctx.set(Paths.user_profile_bio, "Engineer")
        ctx = ctx.set(Paths.search_results, [1, 2, 3])
        ctx = ctx.set(Paths.search_query, "test query")

        assert ctx.get(Paths.user_name) == "Bob"
        assert ctx.get(Paths.user_profile_bio) == "Engineer"
        assert ctx.get(Paths.search_results) == [1, 2, 3]
        assert ctx.get(Paths.search_query) == "test query"


class TestPathBuilder:
    """Tests for dynamic path builder."""

    def test_create_path_builder(self):
        """Create a path builder."""
        user_paths_cls = create_path_builder("user")
        user = user_paths_cls()

        name_path = user.name
        assert isinstance(name_path, ContextPath)
        assert name_path.path == "user.name"

    def test_path_builder_multiple_attributes(self):
        """Access multiple attributes from path builder."""
        tool_paths_cls = create_path_builder("tools.search")
        tools = tool_paths_cls()

        query_path = tools.query
        results_path = tools.results

        assert query_path.path == "tools.search.query"
        assert results_path.path == "tools.search.results"

    def test_path_builder_no_prefix(self):
        """Path builder without prefix."""
        paths_cls = create_path_builder()
        paths = paths_cls()

        root_path = paths.data
        assert root_path.path == "data"

    def test_path_builder_with_context(self):
        """Use path builder with TypedContext."""
        config_paths_cls = create_path_builder("config")
        config = config_paths_cls()

        ctx = TypedContext(Context())
        ctx = ctx.set(config.api_key, "secret123")
        ctx = ctx.set(config.timeout, 30)

        assert ctx.get(config.api_key) == "secret123"
        assert ctx.get(config.timeout) == 30


class TestBackwardCompatibility:
    """Tests for backward compatibility with string paths."""

    def test_mixed_path_types(self):
        """Mix typed paths and string paths."""
        typed_path = ContextPath[str]("user.name")

        ctx = TypedContext(Context())
        ctx = ctx.set(typed_path, "Alice")  # Typed path
        ctx = ctx.set("user.age", 30)  # String path

        assert ctx.get(typed_path) == "Alice"  # Typed path
        assert ctx.get("user.age") == 30  # String path

    def test_raw_context_still_works(self):
        """Raw Context still works as before."""
        raw_ctx = Context()
        raw_ctx = raw_ctx.set("user.name", "Bob")

        # Can wrap in TypedContext
        typed_ctx = TypedContext(raw_ctx)

        assert typed_ctx.get("user.name") == "Bob"

    def test_unwrap_to_raw_context(self):
        """Unwrap TypedContext to get raw Context."""
        typed_ctx = TypedContext(Context())
        typed_ctx = typed_ctx.set("data", "value")

        raw_ctx = typed_ctx.unwrap()

        # Raw context has same data
        assert raw_ctx.get("data") == "value"
        assert isinstance(raw_ctx, Context)


class TestComplexScenarios:
    """Tests for complex real-world scenarios."""

    def test_multi_agent_context(self):
        """Simulate multi-agent context with different namespaces."""

        class AgentPaths:
            # Agent 1 paths
            agent1_task = ContextPath[str]("agents.agent1.task")
            agent1_result = ContextPath[str]("agents.agent1.result")

            # Agent 2 paths
            agent2_task = ContextPath[str]("agents.agent2.task")
            agent2_result = ContextPath[str]("agents.agent2.result")

            # Shared state
            shared_data = ContextPath[dict]("shared.data")

        ctx = TypedContext(Context())
        ctx = ctx.set(AgentPaths.agent1_task, "Research")
        ctx = ctx.set(AgentPaths.agent1_result, "Research complete")
        ctx = ctx.set(AgentPaths.agent2_task, "Write")
        ctx = ctx.set(AgentPaths.agent2_result, "Writing complete")
        ctx = ctx.set(AgentPaths.shared_data, {"status": "running"})

        assert ctx.get(AgentPaths.agent1_task) == "Research"
        assert ctx.get(AgentPaths.agent2_result) == "Writing complete"
        assert ctx.get(AgentPaths.shared_data) == {"status": "running"}

    def test_tool_output_storage(self):
        """Store and retrieve tool outputs."""

        class ToolPaths:
            search_results = ContextPath[list]("tools.search.results")
            scrape_content = ContextPath[str]("tools.scraper.content")
            analysis_score = ContextPath[float]("tools.analyzer.score")

        ctx = TypedContext(Context())
        ctx = ctx.set(ToolPaths.search_results, ["result1", "result2"])
        ctx = ctx.set(ToolPaths.scrape_content, "Scraped content here")
        ctx = ctx.set(ToolPaths.analysis_score, 0.95)

        assert len(ctx.get(ToolPaths.search_results)) == 2
        assert "Scraped content" in ctx.get(ToolPaths.scrape_content)
        assert ctx.get(ToolPaths.analysis_score) == 0.95
