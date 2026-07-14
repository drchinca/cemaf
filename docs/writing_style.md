# Documentation Voice

CEMAF documentation should read like it was written by a senior solution
architect who built the system, knows where the sharp edges are, and does not
need launch-copy language to sound confident.

## Rules

- State what the framework does, what contract it exposes, and what tradeoff it
  makes.
- Keep the voice human. A dry aside is fine when it clarifies the point. Sarcasm
  is not a substitute for evidence.
- Prefer concrete nouns: protocol, context patch, event, budget, replay,
  citation, adapter, factory, service.
- Avoid launch-copy language, praise, and vague claims.
- Avoid "AI assistant" tone. Do not flatter the reader, apologize for ordinary
  constraints, or promise outcomes the code cannot prove.
- Do not be rude. Direct writing should reduce ambiguity, not punch down.
- Mark maturity precisely: implemented, experimental, alpha, beta, stable,
  deprecated.
- When a claim sounds broad, point to a module, spec, example, or test that
  supports it.

## Examples

Use:

- "SQLite-backed persistent memory store via `aiosqlite`."
- "RLM composes with CEMAF agents through the `Tool` protocol."
- "The default provider path is local-first: Ollama for LLMs, hash embeddings
  for retrieval, static catalog metadata."
- "No module-level singleton. Future-you gets one less invisible wire to debug."

Avoid:

- Maturity claims without a named release level or verifier.
- Claims that imply integration has no tradeoffs.
- Market category claims that are not tied to a spec, test, or module.
- Launch-copy adjectives that praise the project instead of describing the
  contract.
- Snark aimed at users, projects, or maintainers. The dry humor should be about
  the engineering situation, not the people in it.
