# Agents

Agents are autonomous entities with goals, memory, and decision-making capabilities.

## Agent Architecture

```mermaid
flowchart TB
    subgraph Agent
        GOAL[Goal<br/>Task objective]
        MEMORY[Memory<br/>State & history]
        DECISION[Decision Loop<br/>Plan & act]
    end

    subgraph Capabilities
        SKILLS[Skills<br/>Composable]
        TOOLS[Tools<br/>Atomic]
        LLM[LLM<br/>Reasoning]
    end

    subgraph Context
        ACTX[AgentContext<br/>Runtime state]
        RESULT[Result T<br/>Output]
    end

    GOAL --> DECISION
    MEMORY --> DECISION
    DECISION --> SKILLS
    DECISION --> TOOLS
    DECISION --> LLM
    SKILLS --> RESULT
    TOOLS --> RESULT
    ACTX --> DECISION
```

## Agent Execution Flow

```mermaid
sequenceDiagram
    participant Orchestrator
    participant Agent
    participant Memory
    participant LLM
    participant Skills/Tools

    Orchestrator->>Agent: run(goal, context)
    Agent->>Memory: Load state

    loop Decision Loop
        Agent->>LLM: Plan next action
        LLM-->>Agent: Action decision
        Agent->>Skills/Tools: Execute action
        Skills/Tools-->>Agent: Action result
        Agent->>Memory: Update state
    end

    Agent-->>Orchestrator: Result
```

## Defining an Agent

```python
from cemaf.agents.base import Agent
from cemaf.core.result import Result

class ResearchAgent(Agent[dict, dict]):
    @property
    def id(self) -> str:
        return "researcher"

    async def run(self, goal: dict, context: AgentContext) -> Result[dict]:
        # Agent logic with memory and decision-making
        return Result.ok({"result": "research complete"})
```
