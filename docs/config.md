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
from cemaf.config.loader import SettingsProvider
from cemaf.config.protocols import EnvConfigSource, DictConfigSource

# Load from environment
env_source = EnvConfigSource(prefix="CEMAF_")

# Load from dict
dict_source = DictConfigSource({"key": "value"})

# Combine sources
provider = SettingsProvider([env_source, dict_source])
settings = provider.get_settings()
```
