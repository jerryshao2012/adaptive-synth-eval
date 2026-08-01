# Documentation

Use this page to choose the shortest path for your task. Configuration details live in the linked guides rather than being repeated here.

## Start here

- [Root quick start](../README.md#quick-start) — New users can install the project and complete the shortest validated dry-run.
- [Simulation contracts](contracts.md) — Evaluation authors can define and validate personas, scenarios, targets, schedules, and outputs.
- [CLI usage](cli_usage.md) — CLI users can find command syntax, flags, recovery options, and realtime controls.
- [One-day time-profile verification](time_profile_verification.md) — Evaluators can validate the Agent Skills profile demo, inspect phase provenance, run monitoring, verify dashboard bands, and smoke-test resume protection in one laptop session.

## Run evaluations

- [Synth user simulation](user_simulation_llm.md) — Scenario authors can generate realistic persona-driven benign conversations with templates or an LLM.
- [Unified evaluation](unified_evaluation.md) — Evaluators can interleave synthetic traffic with adversarial probes and scoring in one run.
- [Adversarial internals](adversarial_agent_walkthrough.md) — Engineers and data scientists can understand the attack planner, generator, judge, and adaptive memory flow.
- [Attack skills](attack_skills.md) — Attack-method authors and operators can configure, inspect, validate, and safely extend curated Agent Skills packages.
- [Realtime chat](cli_usage.md#real-time-chat--interactive-controls) — Operators can watch dry-runs or live evaluations and use terminal session controls.

## Understand outputs

- [Output artifacts and schemas](output_artifacts.md) — Analysts and integrators can locate run files and interpret their record formats.
- [Golden datasets](golden_datasets.md) — Curators and API developers can reuse approved examples across metric-specific collections, publish immutable versions, and export reproducible manifests.
- [Persona memory](persona_memory.md) — Evaluators can understand how persona context is isolated, retained, and updated across conversations.
- [Dashboard setup](../ai-eval-dashboard/README.md) — Reviewers can launch the local dashboard to inspect run and monitoring artifacts.

## Operate continuously

- [Monitoring](monitoring.md) — Evaluation operators can score existing run artifacts, manage incremental re-evaluation, and feed dashboard views.
- [Triggered monitoring implementation](hindsight-implementation-summary.md) — Maintainers can review the conversation-safe selector, durable capture journals, provenance, and current artifact-source scope.
- [Metrics API](metrics_api.md) — Integrators can discover packaged metric specifications and score independent payload tuples through the authenticated Python service.
- [Loop architecture](loop_engineering_for_adversarial_adaptive_synthetic_evaluation.md) — Platform engineers can understand guarded repeat-run coordination and L0-L3 readiness.
- [Loop operations runbook](loop_operations_runbook.md) — On-call operators can start, audit, pause, recover, and safely run continuous evaluations.
- [Governed continuous learning](continuous_learning.md) — Evaluation owners can mine synthetic evidence, compare versioned challengers, approve bounded evaluator improvements, and roll back safely.

## Environment/deployment

- [Environment setup](environment_setup.md) — Developers and operators can configure providers, credentials, proxies, certificates, and supported target environments, with a contextual [dashboard setup reference](../ai-eval-dashboard/README.md) for the local Next.js application.

## Historical

- [Archive index](archive/README.md) — Maintainers and researchers can find superseded plans, implemented design records, and standalone prototypes without confusing them for current guidance.
