# Configuration Module - Extended Documentation

## Overview

The configuration module provides centralized settings management for CEMAF applications, supporting YAML, JSON, environment variables, and hot-reload with multi-source merging.

**What it does**: Implements ConfigSource protocol for loading configuration from different sources (environment, files, dicts, databases). Merges multiple sources with precedence (env overrides file, file overrides defaults). Provides SettingsProvider for accessing typed settings with validation. Supports hot-reload to pick up changes without restart.

**Key use cases**:
- Load settings from environment variables in production
- Load settings from YAML/JSON files in development
- Override specific settings without changing files
- Validate settings on startup (fail fast)
- Support different configs for different environments (dev, staging, prod)
- Change settings without restarting (hot-reload)

**When to use vs. alternatives**: Use config module when you need flexible settings management. Use it for any application with environment-specific configuration. Don't use for secrets (use secrets manager) or dynamic app state (use memory module).

## Core Concepts

### Configuration Sources

**Environment Variables**: CEMAF_LLM_MODEL=claude-3-5-sonnet. Highest priority.

**YAML/JSON Files**: config.yaml with hierarchical structure. Readable in development.

**Dictionary**: Programmatic configuration. Useful for testing.

**Database**: Load settings from DB. Useful for multi-tenant systems.

Sources are merged in priority order:
1. Environment variables (highest)
2. File-based (YAML/JSON)
3. Dictionary/defaults (lowest)

### Settings Types

Each setting has a type (str, int, bool, list, etc.) and optional default. Configuration validates types on load.

```python
class LLMSettings(BaseModel):
    model: str = "claude-3-5-sonnet"
    temperature: float = 0.7
    max_tokens: int = 2000
    api_key: str  # Required, no default
```

### Configuration Namespaces

Settings organized by component:

```yaml
llm:
  model: claude-3-5-sonnet
  temperature: 0.7

retrieval:
  vector_store: pinecone
  embedding_model: text-embedding-3-small

observability:
  log_level: info
  export_interval_seconds: 60
```

## Usage Examples

### Basic Configuration Loading

```python
from cemaf.config import SettingsProvider, EnvConfigSource, DictConfigSource
from pydantic import BaseModel

# Define settings schema
class AppSettings(BaseModel):
    llm_model: str = "claude-3-5-sonnet"
    temperature: float = 0.7
    debug: bool = False

# Create provider with multiple sources
provider = SettingsProvider([
    EnvConfigSource(prefix="APP_"),      # Load from APP_* env vars
    DictConfigSource({"debug": True}),   # Programmatic overrides
])

# Load settings
settings = await provider.get(AppSettings)

print(f"Model: {settings.llm_model}")
print(f"Temperature: {settings.temperature}")
print(f"Debug: {settings.debug}")
```

### YAML Configuration File

```yaml
# config.yaml
app:
  name: ContentGen
  debug: false
  port: 8000

llm:
  model: claude-3-5-sonnet
  temperature: 0.7
  max_tokens: 2000
  api_key: ${OPENAI_API_KEY}  # Reference env var

retrieval:
  vector_store: pinecone
  embedding_model: text-embedding-3-small
  similarity_threshold: 0.7

database:
  url: postgresql://localhost/cemaf
  pool_size: 10
  echo: false

observability:
  log_level: info
  export_format: json
```

Load with:

```python
from cemaf.config import YAMLConfigSource

provider = SettingsProvider([
    YAMLConfigSource("config.yaml"),
    EnvConfigSource(prefix="CEMAF_"),  # Override with env vars
])

settings = await provider.get(AppSettings)
```

### Environment-Specific Configuration

```python
from cemaf.config import ConfigSource, SettingsProvider
import os

def create_provider(environment: str):
    """Create provider for specific environment."""
    env = environment or os.getenv("ENVIRONMENT", "development")

    sources = []

    # Base config
    sources.append(YAMLConfigSource("config.yaml"))

    # Environment-specific override
    env_file = f"config.{env}.yaml"
    if os.path.exists(env_file):
        sources.append(YAMLConfigSource(env_file))

    # Environment variables (highest priority)
    sources.append(EnvConfigSource(prefix="CEMAF_"))

    return SettingsProvider(sources)

# Usage
dev_provider = create_provider("development")
prod_provider = create_provider("production")

dev_settings = await dev_provider.get(AppSettings)
prod_settings = await prod_provider.get(AppSettings)
```

### Typed Settings with Validation

```python
from pydantic import BaseModel, Field, validator
from typing import Optional

class LLMSettings(BaseModel):
    model: str = Field(
        default="claude-3-5-sonnet",
        description="LLM model name"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Temperature (0-2)"
    )
    max_tokens: int = Field(
        default=2000,
        ge=1,
        le=100000,
        description="Max tokens to generate"
    )

    @validator("model")
    def validate_model(cls, v):
        valid_models = [
            "claude-3-5-sonnet",
            "gpt-4",
            "gpt-3.5-turbo"
        ]
        if v not in valid_models:
            raise ValueError(f"Model must be one of {valid_models}")
        return v

# Load and validate
provider = SettingsProvider([EnvConfigSource()])
settings = await provider.get(LLMSettings)

# Raises ValidationError if temperature > 2.0 or model not in list
```

### Hot-Reload Configuration

```python
from cemaf.config import SettingsProvider, HotReloadConfigSource

# Wrap source with hot-reload
config_source = YAMLConfigSource("config.yaml")
hot_reload_source = HotReloadConfigSource(
    source=config_source,
    check_interval_seconds=10  # Check for changes every 10 seconds
)

provider = SettingsProvider([hot_reload_source])

# Settings update automatically
while True:
    settings = await provider.get(AppSettings)
    print(f"Current log level: {settings.log_level}")
    await asyncio.sleep(5)
```

### Configuration Secrets Handling

```python
from pydantic import SecretStr

class SecureSettings(BaseModel):
    api_key: SecretStr  # Won't be logged or printed
    database_password: SecretStr

# Environment variable: CEMAF_API_KEY=secret123
provider = SettingsProvider([EnvConfigSource(prefix="CEMAF_")])
settings = await provider.get(SecureSettings)

# Safe to log - shows ****
print(f"Using API key: {settings.api_key}")  # Output: Using API key: ****
```

### Multi-Tenant Configuration

```python
from cemaf.config import ConfigSource, SettingsProvider

class TenantConfigSource(ConfigSource):
    """Load config for specific tenant."""

    def __init__(self, tenant_id: str, db_connection):
        self.tenant_id = tenant_id
        self.db = db_connection

    async def load(self) -> dict:
        """Load tenant-specific config from database."""
        result = await self.db.query(
            "SELECT settings FROM tenants WHERE id = ?",
            self.tenant_id
        )
        return result[0]["settings"]

# Create provider per tenant
async def get_tenant_settings(tenant_id: str, db):
    sources = [
        TenantConfigSource(tenant_id, db),  # Tenant-specific
        EnvConfigSource(prefix="CEMAF_"),   # Global overrides
    ]
    provider = SettingsProvider(sources)
    return await provider.get(AppSettings)

# Different settings per tenant
tenant1_settings = await get_tenant_settings("tenant_1", db)
tenant2_settings = await get_tenant_settings("tenant_2", db)
```

### Configuration Testing

```python
from cemaf.config import InMemoryConfigSource

@pytest.fixture
async def test_settings():
    """Provide test settings."""
    source = InMemoryConfigSource({
        "llm_model": "mock",
        "debug": True,
        "api_key": "test-key"
    })

    provider = SettingsProvider([source])
    return await provider.get(AppSettings)

async def test_with_custom_config():
    settings = await test_settings()
    assert settings.llm_model == "mock"
    assert settings.debug == True
```

### Common Mistake: Hardcoding Configuration

```python
# ❌ WRONG - Hardcoded settings, can't change
llm_model = "claude-3-5-sonnet"
temperature = 0.7

if llm_model == "claude-3-5-sonnet":
    # Specific logic tied to config value
    ...

# ✅ CORRECT - Load from configuration
provider = SettingsProvider([...])
settings = await provider.get(AppSettings)

if settings.llm_model == "claude-3-5-sonnet":
    # Configurable logic
    ...
```

## Integration

### With Persistence Module

```python
from cemaf.config import SettingsProvider

class ConfiguredStore(RunStore):
    def __init__(self, settings: AppSettings):
        self.settings = settings
        # Use settings to connect to database
        self.db = connect(settings.database.url)
```

### With Observability

```python
from cemaf.config import SettingsProvider
from cemaf.observability.logger import StructuredLogger

async def setup_logging(settings: AppSettings):
    logger = StructuredLogger(
        level=settings.observability.log_level,
        format=settings.observability.log_format
    )
    return logger
```

### With Scheduler

```python
# Scheduler respects configuration
class ConfiguredScheduler:
    def __init__(self, settings: AppSettings):
        self.scheduler = Scheduler()
        self.settings = settings

    async def schedule_jobs(self):
        # Job frequencies from config
        if self.settings.scheduler.enable_daily_cleanup:
            await self.scheduler.schedule(
                Job(
                    name="cleanup",
                    func=cleanup,
                    trigger=CronTrigger(self.settings.scheduler.cleanup_schedule)
                )
            )
```

## API Reference

### ConfigSource Protocol

```python
@runtime_checkable
class ConfigSource(Protocol):
    async def load(self) -> dict:
        """Load configuration. Return dict structure."""
```

### SettingsProvider

```python
class SettingsProvider:
    def __init__(self, sources: list[ConfigSource]):
        """Initialize with configuration sources (priority order)."""

    async def get(self, settings_class: type[T]) -> T:
        """Load and validate settings."""

    async def reload(self) -> None:
        """Reload from sources."""
```

### Built-in Sources

```python
class EnvConfigSource(ConfigSource):
    """Load from environment variables with prefix."""
    def __init__(self, prefix: str = "CEMAF_"): ...

class YAMLConfigSource(ConfigSource):
    """Load from YAML file."""
    def __init__(self, path: str): ...

class JSONConfigSource(ConfigSource):
    """Load from JSON file."""
    def __init__(self, path: str): ...

class DictConfigSource(ConfigSource):
    """Load from dictionary."""
    def __init__(self, config: dict): ...

class InMemoryConfigSource(ConfigSource):
    """In-memory config (for testing)."""
    def __init__(self, data: dict): ...
```

### HotReloadConfigSource

```python
class HotReloadConfigSource(ConfigSource):
    """Wrap another source with hot-reload capability."""
    def __init__(
        self,
        source: ConfigSource,
        check_interval_seconds: int = 10
    ): ...
```

## Best Practices

### Configuration Structure

```yaml
# Organize by concern, not by system
app:
  name: cemaf
  environment: production
  debug: false

llm:
  provider: openai
  model: gpt-4
  temperature: 0.7

storage:
  persistence:
    type: postgresql
    url: ${DATABASE_URL}
  cache:
    type: redis
    url: ${REDIS_URL}

services:
  retrieval:
    vector_store: pinecone
    similarity_threshold: 0.7
  scheduler:
    enabled: true
    max_jobs: 100

observability:
  logging:
    level: info
    format: json
  metrics:
    enabled: true
    export_interval_seconds: 60
```

### Secrets Management

```python
# NEVER store secrets in config files
# ❌ WRONG
api_key: "sk-abc123def456"

# ✅ CORRECT - Reference environment variable
api_key: ${OPENAI_API_KEY}

# In production, use secrets manager
# ✅ BEST - Load from secrets manager
class SecretsSource(ConfigSource):
    async def load(self):
        return await secrets_manager.get("cemaf/prod")
```

### Environment-Specific Config

```
config/
├── config.yaml           # Base config
├── config.development.yaml
├── config.staging.yaml
└── config.production.yaml

# Load: base + environment-specific + env vars
```

### Validation and Defaults

```python
class Settings(BaseModel):
    # With defaults
    debug: bool = False

    # Required
    api_key: str

    # With validation
    max_retries: int = Field(default=3, ge=0, le=10)

    # With description
    log_level: str = Field(
        default="info",
        description="Logging level: debug, info, warning, error"
    )
```

### Performance Tips

- **Lazy loading**: Don't load all settings upfront. Load on demand.
- **Caching**: Cache loaded settings. Reload only when needed.
- **Validation once**: Validate on load, not on every access.

### Common Pitfalls

**Secrets in logs**: Accidentally logging API keys. Use SecretStr.

**Missing validation**: Typos in config files caught late. Validate early.

**No defaults**: Required settings without defaults fail at runtime. Provide sensible defaults.

**Static configuration**: Can't adapt to changes. Use hot-reload for flexibility.

### When NOT to Use

- **Secrets**: Use dedicated secrets manager
- **Dynamic state**: Use memory module
- **User-specific settings**: Use database
- **Real-time metrics**: Use observability module
