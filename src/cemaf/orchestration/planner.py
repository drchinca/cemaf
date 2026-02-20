"""
Autonomous Planner - Generates DAGs dynamically from high-level goals.

The Planner uses an LLM to analyze a goal and generate a step-by-step execution plan
as a CEMAF DAG structure. This enables autonomous workflow orchestration.
"""

import json
import logging
from typing import Any

from cemaf.core.types import NodeID
from cemaf.llm.protocols import LLMClient, LLMConfig, Message
from cemaf.orchestration.dag import DAG, Edge, Node, NodeType  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


class Planner:
    """
    Autonomous planner that generates DAGs from high-level goals.

    Uses an LLM to analyze goals and create execution plans as DAG structures.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        agent_registry: Any,  # AgentRegistry from cemaf.agents.registry
        config: LLMConfig | None = None,
    ):
        self._llm_client = llm_client
        self._agent_registry = agent_registry
        self._config = config

    async def plan(
        self,
        goal: str,
        dag_name: str | None = None,
    ) -> DAG:
        """
        Generate a DAG from a high-level goal.

        Args:
            goal: High-level goal description
            dag_name: Optional name for the generated DAG

        Returns:
            DAG structure ready for execution

        Raises:
            ValueError: If planning fails or produces invalid DAG
        """
        logger.info("Planner activated. Synthesizing execution strategy...")

        # Get capabilities description from registry
        capabilities = self._agent_registry.get_capabilities_description()

        system_prompt = f"""You are the strategic core of the Context Engine. Analyze the
user's high-level GOAL and create a step-by-step EXECUTION PLAN.

AVAILABLE CAPABILITIES
---
{capabilities}
---

INSTRUCTIONS:
1. Output MUST be a single JSON object with a "plan" key containing a list of step objects.
2. Each step object must have:
   - "step": (integer) Step number (1, 2, 3, ...)
   - "agent": (string) Agent name (must be one of: Librarian, Researcher, Summarizer, Writer)
   - "input": (object) Input parameters for the agent, using exact key names from capabilities
3. Use Context Chaining: format placeholders as "$$STEP_N_OUTPUT$$" to reference previous step outputs.
4. Example step:
   {{
     "step": 1,
     "agent": "Librarian",
     "input": {{
       "intent_query": "professional audit report style"
     }}
   }}
5. Example with context chaining:
   {{
     "step": 2,
     "agent": "Researcher",
     "input": {{
       "topic_query": "$$STEP_1_OUTPUT$$"
     }}
   }}

Output only valid JSON, no markdown formatting."""

        try:
            # Call LLM with JSON mode if supported
            config_override = self._config or LLMConfig()
            # Try to enable JSON mode if the client supports it
            if hasattr(config_override, "response_format"):
                config_override.response_format = {"type": "json_object"}

            llm_result = await self._llm_client.complete(
                [Message.system(system_prompt), Message.user(goal)],
                config_override=config_override,
            )

            if not llm_result.success:
                raise ValueError(f"LLM planning failed: {llm_result.error}")

            # Parse JSON response
            if isinstance(llm_result.content, list):
                # If content is a list, extract first element
                plan_json_string = str(llm_result.content[0]) if llm_result.content else "{}"
            else:
                # Content is a string
                plan_json_string = str(llm_result.content)

            # Try to extract JSON from markdown code blocks if present
            if "```json" in plan_json_string:
                start = plan_json_string.find("```json") + 7
                end = plan_json_string.find("```", start)
                plan_json_string = plan_json_string[start:end].strip()
            elif "```" in plan_json_string:
                start = plan_json_string.find("```") + 3
                end = plan_json_string.find("```", start)
                plan_json_string = plan_json_string[start:end].strip()

            plan_data = json.loads(plan_json_string)

            if "plan" not in plan_data:
                raise ValueError("LLM response missing 'plan' key")

            plan_steps = plan_data["plan"]
            if not isinstance(plan_steps, list):
                raise ValueError("Plan must be a list of steps")

            # Convert plan to DAG
            dag = self._plan_to_dag(plan_steps, dag_name or f"PlannedDAG_{len(plan_steps)}_steps")
            logger.info(f"Plan generated successfully with {len(plan_steps)} steps")
            return dag

        except json.JSONDecodeError as e:
            logger.error(f"Planner failed to parse JSON: {e}")
            logger.debug(f"Raw LLM response: {plan_json_string}")
            raise ValueError(f"Invalid JSON from planner: {e}") from e
        except Exception as e:
            logger.error(f"Planner failed to generate plan: {e}", exc_info=True)
            raise

    def _plan_to_dag(self, plan_steps: list[dict[str, Any]], dag_name: str) -> DAG:
        """
        Convert a plan (list of steps) into a CEMAF DAG.

        Args:
            plan_steps: List of step dictionaries with 'step', 'agent', 'input'
            dag_name: Name for the DAG

        Returns:
            Validated DAG structure
        """
        dag = DAG(name=dag_name, description=f"Autonomously planned workflow: {dag_name}")

        previous_node_id: NodeID | None = None

        for step_data in plan_steps:
            step_num = step_data.get("step")
            agent_name = step_data.get("agent")
            input_data = step_data.get("input", {})

            if not step_num or not agent_name:
                raise ValueError(f"Invalid step: missing 'step' or 'agent' in {step_data}")

            # Validate agent name: check registered instances or built-in classes
            known = self._agent_registry.list_agents()
            has_class = (
                hasattr(self._agent_registry, "get_agent_class")
                and self._agent_registry.get_agent_class(agent_name) is not None
            )
            if agent_name not in known and not has_class:
                raise ValueError(f"Unknown agent: {agent_name}. Available: {known}")

            # Create node ID
            node_id = NodeID(f"step_{step_num}")

            # Create agent node with input mapping
            # The input_mapping will be resolved by the executor using regex resolution
            node = Node(
                id=node_id,
                type=NodeType.AGENT,
                name=f"{agent_name} (Step {step_num})",
                description=f"Step {step_num}: {agent_name}",
                ref_id=agent_name,
                input_mapping=input_data,  # This will be resolved by executor
                output_key=f"STEP_{step_num}_OUTPUT",  # Standard output key for context chaining
            )

            dag = dag.add_node(node)

            # Add edge from previous node if exists
            if previous_node_id:
                edge = Edge(source=previous_node_id, target=node_id)
                dag = dag.add_edge(edge)

            previous_node_id = node_id

        # Validate the DAG structure
        dag.validate_structure()
        return dag
