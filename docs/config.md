# Configuration

Configuration management with multiple sources.

## Configuration Architecture

```mermaid
flowchart TB
    subgraph Sources
        ENV[EnvConfigSource<br/>Environment vars]
        DICT[DictConfigSource<br/>In-memory dict]
        FILE[FileConfigSource<br/>Config files]
    end

    subgraph Provider
        PROV[SettingsProvider<br/>Source aggregator]
        MERGE[Merge Strategy<br/>Priority order]
    end

    subgraph Output
        SETTINGS[Settings<br/>Typed config]
    end

    ENV --> PROV
    DICT --> PROV
    FILE --> PROV
    PROV --> MERGE
    MERGE --> SETTINGS
```

## Configuration Flow

```mermaid
sequenceDiagram
    participant App
    participant Provider as SettingsProvider
    participant EnvSource
    participant DictSource
    participant Settings

    App->>Provider: create([env_source, dict_source])

    App->>Provider: get_settings()
    Provider->>EnvSource: load()
    EnvSource-->>Provider: env_config
    Provider->>DictSource: load()
    DictSource-->>Provider: dict_config
    Provider->>Provider: merge(configs)
    Provider-->>App: Settings
```

## Config Sources

```python
from cemaf.config import (
    DictConfigSource,
    EnvConfigSource,
    config_source_registry,
    create_config_source,
    create_settings_provider,
)

# Load from environment
env_source = EnvConfigSource(prefix="CEMAF")

# Load from dict
dict_source = DictConfigSource({"key": "value"})

# Combine direct sources. Higher priority sources override lower priority sources.
provider = create_settings_provider(
    sources=(
        (1, env_source),
        (2, dict_source),
    )
)
settings = await provider.get()

# Declarative source construction through the registry.
provider = create_settings_provider(
    source_specs=(
        {"type": "env", "priority": 1, "prefix": "CEMAF"},
        {"type": "dict", "priority": 2, "data": {"debug": True}},
    )
)

# Custom sources can be registered without changing framework code.
config_source_registry.register(
    backend="consul",
    factory=lambda **kwargs: ConsulConfigSource(url=kwargs["url"]),
)
source = create_config_source("consul", url="https://consul.example")
```
