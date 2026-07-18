# Trajectory-Aware Adaptive Adversarial Evaluation Harness
> **Archive status — Standalone prototype.** Its five-point scale and standalone source are historical prototype behavior, not the current evaluation contract. See the current [unified evaluation documentation](../../../unified_evaluation.md) and [adversarial agent walkthrough](../../../adversarial_agent_walkthrough.md).

## Overview

This project extends the original Adaptive Adversarial Evaluation Harness from a chatbot-focused evaluator into a trajectory-aware evaluator capable of assessing modern agentic and multi-agent AI systems.

The original harness was developed primarily for evaluating enterprise RAG chatbots. Its central objective was to determine whether an adaptive evaluator could gradually move a chatbot toward increasingly risky behavior while operating under realistic enterprise constraints such as guardrails, moderation systems, session controls, and token budgets.

As experimentation expanded beyond traditional RAG chatbots and into agentic systems, a limitation became apparent. Many important failures in agentic systems do not appear in the final user-visible response. Instead, failures may occur inside the execution trajectory through unsafe routing decisions, incorrect agent delegation, inappropriate tool usage, memory contamination, retrieval misuse, or state corruption. A chatbot-focused evaluator can miss these failures entirely.

This package therefore introduces trajectory-aware evaluation while preserving the core adaptive evaluation philosophy of the original harness.

---

# Why This Architecture Is Different

## The Original RAG-Oriented Architecture

The original harness assumed the following evaluation loop:

```text
User Input
    ↓
Target Chatbot
    ↓
Final Response
    ↓
Judge
    ↓
Adaptive Planner
```

The evaluator generated user inputs, observed chatbot responses, judged those responses, and adapted future prompts based on prior outcomes.

This architecture worked well when the primary failure surface was the final response itself, such as:

- Toxic outputs
- Policy violations
- Sensitive information disclosure
- Hallucinations
- Unsafe recommendations

For traditional RAG systems, these failure modes are often directly observable in the chatbot output.

## The Agentic System Problem

Modern agentic systems introduce additional execution layers:

```text
User Input
    ↓
Orchestrator
    ↓
Agent Routing
    ↓
Tool Calls
    ↓
Memory Access
    ↓
Retrieval
    ↓
Additional Agents
    ↓
Final Response
```

A system may behave unsafely even when the final response appears safe.

Examples include:

- Unsafe agent delegation
- Improper routing decisions
- Retrieval of inappropriate information
- Corrupted memory state
- Unauthorized tool usage
- Agent-to-agent contamination

In these cases, evaluating only the final response is insufficient.

---

# Design Philosophy

The goal of this package is not to "break" a system.

Instead, the goal is to map resilience boundaries.

The evaluator continuously asks:

> How far can adaptive pressure move the system before defenses stabilize?

This framing produces richer and more actionable insights than binary pass/fail testing.

The objective is therefore to characterize:

- Response resilience
- Routing resilience
- Tool resilience
- Memory resilience
- Delegation resilience
- Retrieval resilience

under increasing adaptive pressure.

---

# Architectural Evolution

## Original Architecture

```text
Planner
   ↓
Generator
   ↓
Chatbot
   ↓
Judge
   ↓
Session Controller
```

Primary observable:

```text
Final Response
```

Primary output:

```text
Failure / No Failure
```

## New Architecture

```text
Planner
   ↓
Generator
   ↓
Agent System
   ↓
Trace Collection
   ↓
Trace Summarizer
   ↓
Trajectory-Aware Judge
   ↓
Session Controller
```

Primary observables:

```text
Final Response
Execution Trace
Routing Decisions
Tool Calls
Memory Operations
Agent Handoffs
Retrieval Events
```

Primary output:

```text
Severity Boundary Mapping
```

---

# Core Components

## Adaptation Planner

The planner determines the next high-level evaluation strategy.

It observes:

- prior responses
- prior traces
- prior judge scores
- session history

The planner is responsible for adaptive exploration rather than static testing.

## Turn Generator

The generator creates realistic user interactions.

The goal is not to generate obviously adversarial prompts.

Instead, it generates realistic user behavior that can naturally explore system boundaries.

## Target Agent System Client

The target adapter connects the harness to the system under test.

Unlike the original chatbot adapter, the target may return:

```json
{
  "final_response": "...",
  "trace": {}
}
```

The trace may contain:

- agent calls
- handoffs
- tool invocations
- memory operations
- retrieval events
- latency metrics

## Trace Summarizer

Multi-agent traces can become extremely large.

The trace summarizer compresses execution traces into a compact representation suitable for judging.

This reduces cost while preserving important behavioral signals.

## Trajectory-Aware Judge

The judge evaluates both final-response risk and trajectory risk.

Final-response risks include:

- policy breach
- unsafe advice
- information disclosure

Trajectory risks include:

- unsafe delegation
- retrieval misuse
- routing failures
- memory contamination

The overall severity score is derived from both.

## Session Policy Controller

The session controller determines whether to:

- continue the current session
- start a new session
- stop the experiment

This allows the evaluator to adaptively allocate budget across sessions.

---

# Severity Framework

The default framework uses a five-point severity scale.

| Score | Meaning |
|---|---|
| 1 | Safe behavior |
| 2 | Minor concern |
| 3 | Meaningful risk movement |
| 4 | Serious failure |
| 5 | Severe failure |

The goal is not merely to observe score 5.

The goal is to understand how severity evolves as adaptive pressure increases.

---

# Token Budgeting

All evaluation activity consumes budget.

The harness tracks:

- prompt tokens
- completion tokens
- total tokens
- remaining budget

This allows experiments to be analyzed using a cost-versus-risk framework.

Example questions:

- How much budget is required before meaningful risk movement appears?
- Which strategy families are most efficient?
- Which systems resist adaptive pressure most effectively?

---

# Key Metrics

The trajectory-aware harness introduces new metrics beyond traditional chatbot testing.

## Response Metrics

- peak response severity
- average response severity
- refusal rate

## Trajectory Metrics

- peak trace severity
- unsafe delegation score
- tool-call risk score
- routing-risk score
- memory-risk score
- retrieval-risk score

## Operational Metrics

- tokens consumed
- latency
- sessions executed
- turns executed

---

# Example Evaluation Flow

```text
Start Session
      ↓
Generate User Message
      ↓
Execute Target System
      ↓
Collect Trace
      ↓
Summarize Trace
      ↓
Judge Response + Trace
      ↓
Update Session State
      ↓
Continue?
      ↓
Yes → Next Turn
No  → New Session / Stop
```

---

# When To Use This Package

Recommended for:

- Enterprise RAG systems
- Agentic systems
- Multi-agent systems
- Tool-using AI systems
- Workflow orchestration systems
- AI governance evaluations
- Safety and resilience testing

---

# Future Directions

Potential future extensions include:

- Skill-based evaluation libraries
- Coverage-guided strategy exploration
- Multi-strategy planners
- Agent-specific evaluation rubrics
- Automated failure-surface discovery
- Cross-system resilience benchmarking
- Human-in-the-loop review workflows

The current architecture intentionally remains simple. The primary objective is to introduce trajectory awareness while preserving the proven adaptive evaluation framework developed in the original harness.
