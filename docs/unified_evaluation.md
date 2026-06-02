# Unified Evaluation

The unified evaluation pipeline drives both synthetic conversations (ASE) and adversarial probes (ARE) from a single YAML contract. By combining these two modes, you can evaluate the response quality and security of a chatbot in parallel.

## Unified Contract Anatomy

A unified contract defines:
- **suite**: Metadata about the evaluation run.
- **llm**: Default LLM specification (provider, model, credentials, etc.) used for simulation and scoring.
- **target**: Configuration for the target chatbot being evaluated.
- **time_window**: The period and duration over which the synthetic traffic is simulated.
- **persona_pool**: Personas interacting with the chatbot.
- **scenario_catalog**: Synthetic scenarios.
- **adversarial_scenario_catalog**: Adversarial scenarios designed to stress-test the chatbot.
- **eval_plan**: Defines how many conversations to run, the turn limits, and which persona/scenario pairs to execute.
- **scoring**: Weights for synthetic quality scoring and the failure threshold for adversarial turns.

## Schedule Modes

Each entry in the `eval_plan` can configure a `schedule` to control how synthetic (synth) and adversarial (probe) turns are interleaved:

1. **bernoulli** (Default): Samples each turn as synthetic with probability `p_synth` (default `0.3`), and adversarial otherwise.
2. **phased**: Starts with a fixed number of synthetic warmup turns before transitioning entirely to adversarial probes.
   - `warmup_turns`: Number of synthetic turns at the start (default `2`).
3. **min_each**: Ensures that the conversation contains at least a minimum number of both synthetic and adversarial turns.
   - `min_synth`: Minimum synthetic turns.
   - `min_adversarial`: Minimum adversarial turns.
   - `p_synth`: Probability of choosing synthetic when constraints are satisfied.

## Token Budget

To prevent run-away costs when conducting large evaluations, the unified orchestrator enforces a token budget:
- Configured via `run.budget` (e.g. `100000` tokens).
- Tracks prompt and completion tokens for all components (`planner`, `generator`, `judge`, `policy`, `user_simulator`).
- Automatically aborts the evaluation run once the budget is exhausted, preserving all intermediate outputs and summary statistics.

## Output Artifacts

Unified runs write output files under `outputs/runs/<run_id>/`:
- `run_summary.json`: High-level metrics including token usage, component-level costs, safety scores, and failure rates.
- `turns.jsonl`: Detail of every turn including the text, latency, and turn type (`synth` or `adversarial`).
- `scores.jsonl`: Individual turn safety, relevance, groundedness, and adversarial failure scores.
- `adversarial_sessions.jsonl`: Detail of the adversarial planner's state and attack angles.
- `attack_memory.json`: Shared memory registry recording past successful attack angles.
