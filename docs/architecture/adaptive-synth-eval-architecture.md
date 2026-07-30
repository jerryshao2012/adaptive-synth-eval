This diagram shows the current architecture of Adaptive Synthetic Evaluation, or ASE. The easiest way to read it is from top to bottom across three layers: control surfaces, evaluation runtime, and evidence and governance. Solid arrows represent runtime or data flow, while dashed arrows represent scheduling and governed feedback.

Starting at the top, operators and CI systems primarily interact with ASE through the command-line interface. Evaluation behavior is declared in YAML contracts and loop profiles, which keeps configuration separate from execution.

The guarded loop controller coordinates recurring evaluations. It combines scheduling with policy checks, verification, budget limits, readiness levels, and a kill switch. It can repeat evaluations automatically, but it does not bypass the system’s governance controls.

There are two other entry points. The local Next.js dashboard provides monitoring, trace inspection, human review, and golden-dataset curation. Separately, the standalone Metrics API supports stateless single or batch scoring requests. That separation is intentional: the Metrics API reuses the metric evaluator, but it does not depend on the dashboard and does not write evaluation-run artifacts.

Moving into the runtime layer, the contract loader validates the configuration and selects one of two execution modes. A contract containing simulation_suite selects synth mode, while a contract containing suite selects unified mode.

Synth mode generates realistic, persona-driven benign traffic, including controlled variability and failure injection.

Unified mode is the primary evaluation path. It runs conversations concurrently and distributes turns between benign and adversarial behavior. The benign path uses the user simulator, personas, scenarios, and persona memory. The adversarial path uses the Adversarial Response Engine.

The adversarial engine is more than a prompt generator. It maintains a registry of attack skills, selects a strategy based on context, plans and generates the attack, judges the target’s response, and reflects on the outcome. Attack memory allows later turns and runs to adapt based on what has already been observed.

Both paths interact with the target through a common client factory. That abstraction isolates the evaluation engine from the deployment technology of the target. The target can be exposed through an API, a browser workflow, AgentCore, or a supported model provider.

Target responses then flow through the scoring router, which produces turn-level and conversation-level safety and quality signals. Generation, adversarial planning, scoring, and monitoring can use external LLM providers, shown by the clouds on the right.

Monitoring is deliberately separated from the live evaluation path. It reads persisted chat history incrementally, evaluates selected rows using the packaged metric registry, and writes fingerprinted results atomically. The same metric evaluator is reused by the standalone Metrics API, but the two entry points retain different persistence boundaries.

The bottom layer is the evidence and governance plane.

Every evaluation produces a run-scoped directory containing chat history, turns, scores, checkpoints, and the normalized contract. Adaptive state—including capture journals, persona memory, attack memory, and traces—is retained alongside the run.

Monitoring adds machine-generated scores and state, while the dashboard adds human review evidence. Approved reviews can be promoted into schema-version-two golden datasets. These datasets preserve canonical examples, collection-specific annotations, and immutable published versions for reproducible reuse.

Completed synthetic runs can also feed the learning coordinator. Learning follows a champion–challenger process: it mines eligible evidence, proposes bounded changes to evaluation policies or synthetic assets, and evaluates those changes in a controlled tournament. It cannot modify the target application or its model weights, and activating a candidate requires explicit human approval.

Approved bundles and loop state are maintained in auditable registries. A guarded loop resolves an approved bundle only at a run boundary, preserving reproducibility and preventing a policy change from silently altering an evaluation already in progress.

The key architectural point is that ASE separates execution from evidence and governance. We can generate traffic, probe a target, score its behavior, review the results, and improve future evaluations—while keeping the target boundary, monitoring boundary, and human approval boundary explicit.