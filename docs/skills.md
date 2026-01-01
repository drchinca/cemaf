# Skills

Skills are composable capabilities that use tools to accomplish higher-level tasks.

## Skill Architecture

```mermaid
flowchart TB
    subgraph Skill Definition
        SKILL[Skill<br/>id, execute]
        TOOLS[Tools<br/>Atomic functions]
        CTX[SkillContext<br/>Runtime context]
    end

    subgraph Execution
        INPUT[Input<br/>Typed input]
        PROCESS[Process<br/>Orchestrate tools]
        RESULT[Result T<br/>Typed output]
    end

    SKILL --> TOOLS
    SKILL --> CTX
    INPUT --> PROCESS
    TOOLS --> PROCESS
    CTX --> PROCESS
    PROCESS --> RESULT
```

## Skill Execution Flow

```mermaid
sequenceDiagram
    participant Caller
    participant Skill
    participant Tool1
    participant Tool2
    participant Context as SkillContext

    Caller->>Skill: execute(input, context)
    Skill->>Context: Get runtime info
    Skill->>Tool1: execute(args)
    Tool1-->>Skill: Result

    alt Tool1 Success
        Skill->>Tool2: execute(args)
        Tool2-->>Skill: Result
        Skill-->>Caller: Result.ok(data)
    else Tool1 Failure
        Skill-->>Caller: Result.fail(error)
    end
```

## Defining a Skill

```python
from cemaf.skills.base import Skill
from cemaf.core.result import Result

class ResearchSkill(Skill[str, dict]):
    @property
    def id(self) -> str:
        return "research"

    async def execute(self, input: str, context: SkillContext) -> Result[dict]:
        # Use tools to accomplish the skill
        search_result = await self._search_tool.execute(query=input)
        if not search_result.success:
            return Result.fail("Search failed")

        # Process and return
        return Result.ok({"research": search_result.data})
```
