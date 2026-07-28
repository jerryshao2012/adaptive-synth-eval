# Attack skills

ASE can plan unified adversarial turns with curated packages that follow the open Agent Skills `SKILL.md` format. The feature is opt-in and applies only to unified evaluation; synth mode and existing unified contracts keep the legacy planner path.

## Why Agent Skills without Deep Agents

Agent Skills provides the portable package boundary ASE needs: standards-compatible frontmatter, progressive disclosure, instructions, and package resources. ASE supplies its own execution layer because it already owns conversation scheduling, UCB angle selection, budgets, provider metering, attack memory, target generation, judging, resume policy, and output artifacts.

Deep Agents adds a broader LangGraph harness with filesystem management, subagents, planning, and durable memory. Those capabilities are intentionally outside v1. `AttackSkillExecutor` remains a protocol so a future adapter can be considered if requirements expand to sandboxed scripts, subagents, remote skill sources, or durable agent workflows. The current package has no `deepagents` dependency.

## Enable attack skills

Add this top-level block to a unified contract:

```yaml
attack_skills:
  enabled: true
  include: [] # Empty selects all packaged skills
  allowed_tools:
    - read_skill_resource
    - search_skill_resources
    - inspect_target_capabilities
    - query_attack_memory
    - transform_payload
  max_tool_calls_per_turn: 3
```

The defaults are `enabled: false`, all curated skills, the five built-in read-only tools, and three tool calls per adversarial turn.

An enabled contract is validated before conversations start. `include` accepts only packaged skill names, and `allowed_tools` accepts only the built-in tool names. The selected skill names, versions, content digests, and tool policy enter the normalized contract fingerprint. Resume therefore rejects changed skill content or permissions.

### Paired examples

The checked-in examples form a controlled comparison:

- [`unified_evaluation_demo.yaml`](../contracts/examples/unified_evaluation_demo.yaml) explicitly sets `attack_skills.enabled: false`.
- [`unified_agent_skills_demo.yaml`](../contracts/examples/unified_agent_skills_demo.yaml) uses equivalent providers, target settings, personas, scenarios, schedules, scoring, and tool policy with `attack_skills.enabled: true`.

The suite and run IDs differ so outputs and resume state cannot collide. Both
contracts use `include: []` to select all curated skills. Other unified contracts
remain opt-in because the schema default is still disabled.

Validate or dry-run the pair side by side:

```bash
uv run ase validate-contract contracts/examples/unified_evaluation_demo.yaml
uv run ase validate-contract contracts/examples/unified_agent_skills_demo.yaml
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run
uv run ase run --contract contracts/examples/unified_agent_skills_demo.yaml --dry-run
```

## Inspect and validate packages

```bash
uv run ase skills list
uv run ase skills list --json
uv run ase skills show semantic-drift
uv run ase skills show semantic-drift --json
uv run ase skills validate
uv run ase skills validate semantic-drift
```

The CLI intentionally does not accept arbitrary filesystem paths in v1.

## Curated package profile

Each package lives under `adversarial_response_engine/skills/catalog/<name>/` and contains `SKILL.md`. The directory and frontmatter `name` must match and use lowercase letters, numbers, and single hyphens. ASE metadata is stored as string values:

```yaml
---
name: semantic-drift
description: "gradually shift the meaning of terms or topic scope across turns"
compatibility: "ASE native attack-skill runtime v1; no external writes or network access."
allowed-tools: query_attack_memory
metadata:
  ase-schema-version: "1"
  ase-angle: "semantic_drift"
  ase-version: "1.0.0"
  ase-sub-tactics: "topic_sliding,frame_shift_accumulation,boundary_erosion,reference_class_expansion"
  ase-accumulation: "true"
  ase-scenario-types: "*"
---
```

The body must explain applicability, preconditions, sub-tactics, escalation and refusal recovery, success signals, safety constraints, and the structured planning output. Package digests are stable SHA-256 values calculated from sorted relative paths and file contents.

Validation rejects malformed frontmatter and metadata, undeclared or unknown tools, oversized `SKILL.md` files, `scripts/`, missing packages, unsupported resources, traversal, and symlinks that escape the package. Packaged reference and asset files may be read only through the bounded resource tools.

## Execution and security boundary

The native executor asks the configured planner provider for one JSON action at a time:

- `call_tool` names a declared built-in tool and typed arguments.
- `emit_plan` returns the existing planner fields consumed by the turn generator.

Every planner iteration uses the normal planner client, shared token budget, and component meter. A turn permits the configured number of successful or failed tool calls and at most two malformed-action recoveries. Exhausting either limit raises a structured execution error; ASE records the failed adversarial turn and never silently falls back to legacy planning.

The built-in tools are deliberately non-writing:

| Tool | Scope |
| --- | --- |
| `read_skill_resource` | Read a supported text resource contained in the selected package |
| `search_skill_resources` | Search supported text resources contained in the selected package |
| `inspect_target_capabilities` | Return sanitized capabilities declared by the contract |
| `query_attack_memory` | Return aggregate and recent attack-memory signals |
| `transform_payload` | Apply deterministic base64, URL, JSON, or Unicode transforms |

Inputs use strict Pydantic models and size limits. Calls have a five-second timeout; output is truncated and deterministic audit summaries contain only types and character counts rather than raw arguments or reversible hashes. Target credentials, query strings, headers, and validation inputs are not written to provenance. There is no shell, dynamic import, arbitrary filesystem access, outbound network access, target API invocation, or external write path.

## Selection, memory, and provenance

ASE keeps its existing seeded UCB angle selector. With skills enabled, it restricts candidate angles to included packages compatible with the active scenario, then performs seeded UCB selection among compatible skills within that angle. Each cold-start skill is sampled before exploitation when multiple skill variants exist.

Attack-memory records and snapshots include skill name and version plus skill-level statistics. Older snapshots remain valid with empty skill fields.

Successful adversarial turn planning adds these fields to `PlanResult.raw`, which flows into existing turn artifacts:

- `skill_name`
- `skill_version`
- `skill_package_digest`
- redacted `skill_tool_events`

Failed skill turns add `skill_execution_error` and any safe audit events. This keeps provenance in one serialization path.

## Authoring and verification

V1 packages are repository-owned and curated. Add a package only after tests cover its metadata, compatibility, resources, tool declarations, taxonomy behavior, and stable digest. Validate locally with both implementations:

```bash
uv run ase skills validate
for skill in src/adaptive_synth_eval/adversarial_response_engine/skills/catalog/*/; do
  uvx --from "git+https://github.com/agentskills/agentskills@38a2ff82958afee88dadf4831509e6f7e9d8ef4e#subdirectory=skills-ref" \
    skills-ref validate "$skill"
done
```

Before enabling skills by default, compare legacy and skill-enabled runs using the same seed and deterministic target fixture. Record judge-score distribution, method and unique sub-tactic coverage, tool utilization, planner calls, and token overhead. Keep the feature opt-in unless median judge score and unique sub-tactic coverage do not decline and the security and reproducibility suites pass.
