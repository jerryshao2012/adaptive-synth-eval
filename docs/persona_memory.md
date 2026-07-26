# Persona Memory

Persona memory gives each simulated user a persistent profile and bounded conversation history within one evaluation run. Synth and unified modes use the same `PersonaMarkdownMemory` implementation.

This is distinct from adversarial attack memory: persona memory shapes the simulated user's continuity, while attack memory teaches the adversarial planner which strategies produced useful outcomes.

## Location and isolation

Each persona has a Markdown file:

```text
outputs/runs/<run_id>/personas/<persona_id>_memory.md
```

The actual base directory follows `output.base_dir`. Files are isolated by run and persona, preventing one run's profile from becoming another run's context.

At the start of a conversation, the simulator loads the persona file, initializes missing baseline demographics from the contract, and clears any stale recent window. Long-term profile fields and prior conversation recall remain available.

## File structure

```markdown
# Persona Memory: <persona_id>

## Demographics
- role: <value>
- location: <value>
- seniority: <value>
- style: <value>
- hr_familiarity: <value>
- privacy_sensitivity: <value>

## Preferences
- stated_preference: <value>

## Settings
- language: <value>

## Summary Notes
- User: <evicted message excerpt>

## Long Term Recall
- Interacted regarding <domain> to <intent>. Key message: '<opening message>'

## Recent Window
- User: <message>
- Assistant: <response>
```

The parser tolerates absent sections and values. If the file is missing or unreadable, the simulator starts from an empty memory object and repopulates contract baseline fields.

## Lifecycle

### During a conversation

The simulator appends user and assistant messages to `Recent Window`. When in-memory history exceeds ten messages, it keeps the most recent pair and evicts a lower-importance older message. That excerpt is appended to `Summary Notes`, which is capped at ten entries.

Regex-based profile extraction can update:

- demographics: name, age, location, email, and phone;
- preferences: favorites and a stated preference;
- settings: language.

These updates are heuristic. Treat the memory file as generated evaluation context, not as a verified user profile.

### At conversation completion

The simulator appends a deterministic interaction summary to `Long Term Recall`, capped at twenty entries, then clears `Recent Window`. A later conversation for the same persona starts as a fresh contact while retaining profile fields, summary notes, and long-term recall.

### Prompt injection

Before an LLM-backed synth turn, the simulator renders non-empty demographics, preferences, settings, summary notes, and long-term recall into a persona-context block. The block is prepended to ordinary conversation history; it does not replace the contract persona or scenario.

## Concurrency and writes

The legacy synth runner serializes conversations per persona with an `asyncio.Lock`.
Its Markdown reads and writes also use a process-wide file lock and atomic replacement.

Unified runs instead create one run-scoped persona-memory actor per persona. Each
conversation receives a snapshot when it starts and returns only its delta. The actor
merges deltas in deterministic plan order and persists a versioned JSON source of truth
before rendering the Markdown compatibility view. Concurrent same-persona
conversations therefore do not overwrite one another. They do not see one another's
in-flight changes; a newly starting conversation sees the durable state available at
that time.

The JSON sidecar retains every conversation update for resume and audit. The merged
prompt/Markdown view preserves the existing limits of ten summary notes and twenty
long-term recall entries. These safeguards are process-local, so do not point multiple
ASE processes at the same run directory.

## Privacy considerations

Persona memory may contain synthetic names, email addresses, phone numbers, preferences, and conversation excerpts. Apply the same retention and access controls used for the rest of the run artifacts, especially when a target echoes real-looking identifiers.

When `ASE_CAPTURE_ENABLED=true`, a successful unified persona-memory commit
also emits an optional capture envelope. Authoritative JSON/Markdown
persistence happens first; capture failure is logged without rolling back
memory. Rich deltas use the bounded per-producer buffer and compact skeletons
reference their durable locators.

## Related documentation

- [User simulation LLM](user_simulation_llm.md) — how memory enters simulator prompts.
- [Contract reference](contracts.md) — persona and output configuration.
- [Output artifacts](output_artifacts.md) — run directory and chat-history schemas.
- [Environment setup](environment_setup.md) — local filesystem and platform considerations.
