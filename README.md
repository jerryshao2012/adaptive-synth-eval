# Adversarial Adaptive Synthetic Evaluation

A Python CLI tool for generating synthetic multi-turn chat histories and performing adversarial red-teaming to evaluate HR policy chatbots. This local-first, contract-driven simulation engine creates realistic conversation data without requiring production telemetry or external dependencies.

## 🎯 Overview

Adversarial Adaptive Synthetic Eval helps you:
- **Generate realistic test data**: Create thousands of diverse, persona-driven conversations.
- **Test chatbot behavior**: Validate responses across different user types, scenarios, and edge cases.
- **Inject failures**: Simulate ambiguous queries, typos, frustration, and policy boundary pressure.
- **Evaluate at scale**: Run concurrent simulations with configurable traffic patterns.
- **Red-team chatbots**: Perform adversarial red-teaming to uncover vulnerabilities.
- **Run continuous loops**: Autonomously discover evaluation targets, apply constrained recoveries, and run unattended with safety guardrails (L1/L2/L3 readiness levels).

---

## 🏗️ Architecture

```mermaid
graph TB
    subgraph CLI["CLI Entry Point"]
        Validate["validate-contract"]
        Run["run --contract"]
        Summarize["summarize --run-id"]
        LoopInit["loop init"]
        LoopRun["loop run"]
        LoopStart["loop start --all"]
        LoopAudit["loop audit"]
        LoopPause["loop pause/resume"]
    end

    subgraph ContractLayer["Contract Layer"]
        ContractParser["Contract Parser<br/>YAML/JSON"]
        Validator["Contract Validator<br/>Schema Check"]
        EnvResolver["Environment Resolver<br/>${VAR} substitution"]
    end

    subgraph StaticExec["Static Execution (L0)"]
        GenEngine["Generation Engine<br/>Persona + Scenario"]
        SimEngine["Simulation Engine<br/>Turn-by-turn chat"]
        ScoringEngine["Scoring Engine<br/>Verdict + Metrics"]
    end

    subgraph LoopExec["Loop Execution (L1-L3)"]
        LoopProfiles["Loop Profiles<br/>L1|L2|L3"]
        Scheduler["Multi-Profile Scheduler<br/>Priority + Backoff"]
        Planner["Planner<br/>AI target selection"]
        Policy["Policy Engine<br/>Assisted actions"]
        Verifier["Verifier/Checker<br/>Approval gates"]
        StateStore["State Store<br/>Pause + Budget"]
    end

    subgraph AdversarialExec["Adversarial Red-Teaming"]
        RedTeamEngine["Red-Team Engine<br/>Adaptive attacks"]
        SafetyJudge["Safety Judge<br/>Violation scoring"]
        AdversaryActors["Adversary Actors<br/>Escalation rules"]
        ReflectionEngine["Reflection Engine<br/>Outcome analysis"]
    end

    subgraph LLMClients["LLM Clients & Backends"]
        AzureOpenAI["Azure OpenAI<br/>GPT-4/3.5"]
        AWSBedrock["AWS Bedrock<br/>Claude/Llama"]
        Ollama["Ollama<br/>Local Models"]
        OpenAIAPI["OpenAI API<br/>GPT-4/3.5"]
        Anthropic["Anthropic<br/>Claude"]
    end

    subgraph Persistence["Artifact Persistence"]
        ChatHistory["chat_history.jsonl<br/>Conversations"]
        RunState["run_state.json<br/>Checkpoint"]
        LoopState["loop-state.json<br/>Profile state"]
        LoopBudget["loop-budget.md<br/>Cap tracking"]
        LoopLog["loop-run-log.md<br/>Event log"]
        StateArtifacts["STATE.md<br/>Human summary"]
    end

    subgraph Targets["Evaluation Targets"]
        ChatbotEndpoint["Chatbot Endpoint<br/>HTTP/REST"]
        BrowserUI["Browser UI<br/>Playwright"]
        AgentCore["Agent/Core API<br/>Direct SDK"]
    end

    CLI --> ContractLayer
    ContractLayer --> Validator
    Validator --> StaticExec
    Validator --> LoopExec
    Validator --> AdversarialExec

    StaticExec --> GenEngine
    GenEngine --> SimEngine
    SimEngine --> ScoringEngine
    ScoringEngine --> Persistence

    LoopExec --> LoopProfiles
    LoopProfiles --> Scheduler
    Scheduler --> Planner
    Planner --> Policy
    Policy --> Verifier
    Verifier --> StateStore
    StateStore --> Persistence

    AdversarialExec --> RedTeamEngine
    RedTeamEngine --> SafetyJudge
    SafetyJudge --> AdversaryActors
    AdversaryActors --> ReflectionEngine
    ReflectionEngine --> Persistence

    Planner -.LLM Reasoning.-> LLMClients
    ReflectionEngine -.LLM Reasoning.-> LLMClients
    SafetyJudge -.LLM Judgment.-> LLMClients
    GenEngine -.LLM Messages.-> LLMClients

    SimEngine --> Targets
    RedTeamEngine --> Targets
    Targets -.Responses.-> ScoringEngine

    style CLI fill:#e1f5ff
    style ContractLayer fill:#f3e5f5
    style StaticExec fill:#e8f5e9
    style LoopExec fill:#fff3e0
    style AdversarialExec fill:#fce4ec
    style LLMClients fill:#f1f8e9
    style Persistence fill:#eceff1
    style Targets fill:#ede7f6
```

---

## 📋 Table of Contents

- [Setup](#setup)
- [Quick Start](#quick-start)
- [Detailed Documentation](#detailed-documentation)
- [Project Structure](#project-structure)
- [Testing](#testing)

---

## Setup

### Prerequisites

1. **Python 3.11+**
2. **uv package manager** (recommended)

#### Install uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Alternative via pip
pip install uv
```

### Project Setup

1. Copy the example environment file and configure your settings:
   ```bash
   cp src/.env.example src/.env
   ```
2. Edit `src/.env` and fill in your API keys and endpoints.
3. Install package and local dependencies:
   ```bash
   uv sync
   ```

To make the `ase` command available globally in your workspace without prefixing `uv run`, run:
```bash
uv tool install --editable .
```

---

## Quick Start

### 1. Validate a Contract

```bash
uv run ase validate-contract contracts/examples/unified_evaluation_demo.yaml
```

### 2. Run a Dry-Run Simulation

Test your contract without making real chatbot API calls:

```bash
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run
```

### 3. Stream Realtime Chat

Watch conversations unfold live in your terminal with interactive controls (speed up, pause, switch personas, alter user styles):

```bash
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run --realtime-chat
```

If a previous run with the same `run_id` was interrupted, choose recovery behavior explicitly:

```bash
# Continue remaining conversations from checkpoint state
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --incomplete-run-action resume

# Start over and clean prior artifacts for that run_id
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --incomplete-run-action restart
```

### 4. Summarize a Run

```bash
uv run ase summarize --run-id unified_evaluation_demo_run
```

---

## Detailed Documentation

Detailed guides covering all components and configuration reference are available in the [docs/](./docs) directory:

- [**Simulation Contracts Guide**](./docs/contracts.md): Complete schema reference for YAML contracts, personas, scenarios, traffic patterns, and validation.
- [**CLI Usage & Commands Guide**](./docs/cli_usage.md): Reference for `ase` commands, arguments, interactive real-time controllers, and corporate proxy/SSL configuration.
- [**LLM User Simulation Guide**](./docs/user_simulation_llm.md): Dynamic message generation setup utilizing Azure OpenAI, Ollama, Anthropic, or OpenAI.
- [**Unified & Adversarial Evaluation**](./docs/unified_evaluation.md): Red-teaming and safety testing with adaptive planners, safety judges, and schedules.
- [**Adversarial Agent Walkthrough**](./docs/adversarial_agent_walkthrough.md): Technical deep-dive walkthrough of the adaptive adversarial red-teaming engine, actors, and algorithms.
- [**Persona Memory System**](./docs/persona_memory.md): isolated, markdown-based memory tracking that evolves across conversation sessions.
- [**Output Schema & Artifacts**](./docs/output_artifacts.md): Folder structures and detailed column definitions for output `chat_history` files.
- [**Loop Engineering**](./docs/loop_engineering_for_adversarial_adaptive_synthetic_evaluation.md): Continuous evaluation loops with AI-driven discovery, assisted actions, and unattended execution (L0–L3).
- [**Loop Operations Runbook**](./docs/loop_operations_runbook.md): Production operations guide for unattended loop scheduling, kill switches, and recovery.

---

## Project Structure

```text
adaptive-synth-eval/
├── contracts/examples/      # Example simulation contracts (e.g. unified_evaluation_demo.yaml)
├── docs/                    # Detailed markdown documentation
├── outputs/runs/            # Generated simulation output runs
├── src/adaptive_synth_eval/ # Main source package (cli, clients, engines, generation, scoring)
└── tests/                   # Pytest test suite (unit and integration tests)
```

---

## Testing

Run the test suite using pytest:
```bash
uv run pytest
```
