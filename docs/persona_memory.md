# Persistent Persona Memory System

The `adaptive-synth-eval` tool features a persistent, isolated persona memory system. This allows personas to retain context across conversations and runs, mimicking how a real human remembers demographics, preferences, settings, and prior interactions.

---

## Core Architecture

Each persona's memory is encapsulated in a dedicated markdown file.
- **Path**: `outputs/runs/<run_id>/personas/<persona_id>_memory.md`
- **Isolation**: Each test run maintains its own isolated directories to prevent cross-contamination.
- **Lifecycle**: The memory is loaded at the start of a conversation, updated dynamically during conversation turns, and written atomically back to the markdown file.

---

## Memory Markdown Structure

The markdown memory file contains six key sections:

```markdown
# Persona Memory: <persona_id>

## Demographics
- role: <value>
- location: <value>
- seniority: <value>
- style: <value>
- hr_familiarity: <value>
- privacy_sensitivity: <value>
- email: <extracted_value>

## Preferences
- stated_preference: <extracted_value>

## Settings
- language: <extracted_value>

## Summary Notes
- User: <evicted turn message>
- Assistant: <evicted turn response>

## Long Term Recall
- Interacted regarding <intent> to <topic>. Key message: '<summary>'

## Recent Window
- User: <message>
- Assistant: <response>
```

### Description of Sections:

1. **Demographics**: Tracks user profile demographics. Initial values are populated from the persona's contract baseline configuration, and can be updated dynamically if new information is mentioned (e.g., name, email).
2. **Preferences**: Stored custom preference properties updated dynamically during conversation (e.g., dental coverage choices).
3. **Settings**: Stored configuration/technical properties (e.g., preferred language).
4. **Summary Notes**: If the `Recent Window` exceeds 10 turns, less important turns are evicted and appended here as bullet points to keep the LLM context size bounded.
5. **Long Term Recall**: When a conversation is completed, the simulator generates a high-level summary of the interaction and appends it here.
6. **Recent Window**: The active sliding window of the current conversation. **Note**: This section is cleared at the end of each session/conversation, ensuring that a new conversation starts with a clean slate, but still benefits from the `Long Term Recall` and updated profile attributes.

---

## Profile Delta Extraction

During conversation turns, the simulator uses regular expressions to detect user and assistant updates and dynamically populates/overwrites properties under `Demographics`, `Preferences`, and `Settings`:

- **Preferred Language**: Matches patterns like `\b(?:speak|use) ([a-zA-Z]{2,20})\b` (e.g., "speak French" extracts `language: french`).
- **Emails**: Matches standard email addresses and updates `email` in demographics.
- **Preferences**: Matches phrases like `prefer ([a-zA-Z0-9_\s]{2,40})` to update `stated_preference` under `Preferences`.
- **Names**: Matches patterns like `my name is ([a-zA-Z]{2,20})` to update `name` in demographics.

---

## Memory Context Prompt Injection

When generating a turn, the `UserSimulator` automatically compiles the parsed memory state into a clean context block and prepends it to the LLM system prompt:

```text
[PERSONA CONTEXT]
Demographics: {'role': 'tester', 'location': 'Canada', ...}
Preferences: {'stated_preference': 'standard dental coverage'}
Settings: {'language': 'french'}
Summary Notes:
- Assistant: ...
Long Term Recall:
- Interacted regarding spouse_benefits ...
```

---

## Thread Safety & Robustness

To support high-concurrency evaluation runs, the memory system employs multiple layers of safety:
- **Thread Locks**: A global lock registry maintains a threading lock (`threading.Lock`) per memory file path to prevent concurrent read/write corruptions across parallel simulation threads.
- **Atomic Replacement**: Saves are done by writing to a temporary file (`<filename>.md.tmp`) first and performing an atomic rename/replace.
- **Graceful Error Handling**: If a memory file is corrupted or unreadable, the simulator defaults to a blank state rather than crashing the run.
