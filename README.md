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
    subgraph CLI["CLI Entry Point (cli.py)"]
        Validate["validate-contract"]
        Run["run --contract"]
        Summarize["summarize --run-id"]
        LoopInit["loop init"]
        LoopStart["loop start --all"]
    end

    subgraph ContractLayer["Contract Layer (config/)"]
        ContractParser["Contract Parser"]
        Validator["Contract Validator"]
        EnvResolver["Environment Resolver"]
    end

    subgraph UnifiedEval["Unified Evaluation (unified_eval/)"]
        Orchestrator["Orchestrator"]
        UnifiedPersonas["Personas Engine"]
        UnifiedProviders["Providers Factory"]
        UnifiedScoring["Scoring Engine"]
    end

    subgraph StaticExec["Synth Execution (engines/, generation/)"]
        GenEngine["Generation Engine"]
        SimEngine["Simulation Engine"]
        LegacyScoring["Legacy Scoring"]
    end

    subgraph LoopExec["Loop Execution (loop/)"]
        LoopProfiles["Loop Profiles"]
        Scheduler["Multi-Profile Scheduler"]
        Planner["Planner"]
        Policy["Policy Engine"]
        Verifier["Verifier/Checker"]
        StateStore["State Store"]
    end

    subgraph AdversarialExec["Adversarial Red-Teaming (adversarial_response_engine/)"]
        RedTeamEngine["Red-Team Engine"]
        SafetyJudge["Safety Judge"]
        AdversaryActors["Adversary Actors"]
        ReflectionEngine["Reflection Engine"]
    end

    subgraph LLMClients["LLM Clients & Backends (clients/)"]
        AzureOpenAI["Azure OpenAI"]
        AWSBedrock["AWS Bedrock"]
        Ollama["Ollama"]
        OpenAIAPI["OpenAI API"]
        Anthropic["Anthropic"]
    end

    subgraph Persistence["Artifact Persistence (artifacts/, outputs/)"]
        ChatHistory["chat_history.jsonl"]
        RunState["run_state.json"]
        LoopState["loop-state.json"]
        StateArtifacts["STATE.md"]
    end

    subgraph Targets["Evaluation Targets"]
        ChatbotEndpoint["Chatbot Endpoint"]
        BrowserUI["Browser UI"]
        AgentCore["Agent/Core API"]
    end

    CLI --> ContractLayer
    ContractLayer --> Validator
    
    Validator --> UnifiedEval
    Validator --> StaticExec
    Validator --> LoopExec
    Validator --> AdversarialExec

    UnifiedEval --> Orchestrator
    Orchestrator --> UnifiedPersonas
    UnifiedPersonas --> UnifiedProviders
    UnifiedProviders --> Targets
    Targets --> UnifiedScoring
    UnifiedScoring --> Persistence

    StaticExec --> GenEngine
    GenEngine --> SimEngine
    SimEngine --> LegacyScoring
    LegacyScoring --> Persistence

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
    UnifiedPersonas -.LLM Messages.-> LLMClients
    UnifiedScoring -.LLM Evaluation.-> LLMClients

    SimEngine --> Targets
    RedTeamEngine --> Targets
    
    style CLI fill:#e1f5ff,stroke:#333,stroke-width:1px,color:#000
    style ContractLayer fill:#f3e5f5,stroke:#333,stroke-width:1px,color:#000
    style UnifiedEval fill:#e8eaf6,stroke:#333,stroke-width:1px,color:#000
    style StaticExec fill:#e8f5e9,stroke:#333,stroke-width:1px,color:#000
    style LoopExec fill:#fff3e0,stroke:#333,stroke-width:1px,color:#000
    style AdversarialExec fill:#fce4ec,stroke:#333,stroke-width:1px,color:#000
    style LLMClients fill:#f1f8e9,stroke:#333,stroke-width:1px,color:#000
    style Persistence fill:#eceff1,stroke:#333,stroke-width:1px,color:#000
    style Targets fill:#ede7f6,stroke:#333,stroke-width:1px,color:#000
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
├── contracts/
│   └── examples/                  # Example YAML contracts and test configs
├── docs/                          # User guides, architecture notes, and runbooks
│   └── trajectory_aware_adaptive_eval_harness/
├── examples/                      # Small runnable demo scripts
├── loops/
│   └── profiles/                  # Continuous evaluation loop profiles
├── outputs/
│   └── runs/                      # Generated run artifacts (one folder per run_id)
├── src/
│   └── adaptive_synth_eval/       # Main package
│       ├── adversarial_response_engine/
│       ├── artifacts/
│       ├── clients/
│       ├── config/
│       ├── engines/
│       ├── evaluation/
│       ├── generation/
│       ├── loop/
│       ├── scoring/
│       └── unified_eval/
└── tests/
    ├── integration/               # End-to-end and CLI workflow tests
    └── unit/                      # Component and utility tests
```

---

## Testing

Run the test suite using pytest:
```bash
uv run pytest
```
