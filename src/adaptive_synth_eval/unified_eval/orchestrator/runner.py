"""Top-level fan-out: plans conversations from a UnifiedContract, runs them concurrently,
writes unified artifacts.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections import deque
from dataclasses import asdict
from typing import Any

from adaptive_synth_eval.adversarial_response_engine.core.models import AttackMemory
from adaptive_synth_eval.adversarial_response_engine.core.token_budget import TokenBudgetManager
from adaptive_synth_eval.clients.chatbot_factory import create_chatbot_client
from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController
from adaptive_synth_eval.unified_eval.config.contract import contract_to_dict
from adaptive_synth_eval.unified_eval.config.schemas import UnifiedContract
from adaptive_synth_eval.unified_eval.orchestrator.coin_flip import make_conversation_rng
from adaptive_synth_eval.unified_eval.orchestrator.conversation import (
    ConversationResult,
    run_conversation,
)
from adaptive_synth_eval.unified_eval.output.writer import UnifiedArtifactWriter
from adaptive_synth_eval.unified_eval.providers.budget_meter import BudgetMeter
from adaptive_synth_eval.unified_eval.providers.llm_factory import build_component_llms
from adaptive_synth_eval.unified_eval.providers.llm_target_client import LLMTargetClient

logger = logging.getLogger(__name__)


def run_unified(
        contract: UnifiedContract,
        *,
        dry_run: bool = False,
        persona_filter: str | None = None,
        scenario_filter: str | None = None,
        adversarial_filter: str | None = None,
        max_concurrency_override: int | None = None,
        run_id_override: str | None = None,
        realtime_chat: bool = False,
        output_conversations: bool = False,
        interactive_realtime_controls: bool = False,
) -> dict[str, Any]:
    """Synchronous entry — wraps the async runner for the CLI."""
    return asyncio.run(run_unified_async(
        contract,
        dry_run=dry_run,
        persona_filter=persona_filter,
        scenario_filter=scenario_filter,
        adversarial_filter=adversarial_filter,
        max_concurrency_override=max_concurrency_override,
        run_id_override=run_id_override,
        realtime_chat=realtime_chat,
        output_conversations=output_conversations,
        interactive_realtime_controls=interactive_realtime_controls,
    ))


async def run_unified_async(
        contract: UnifiedContract,
        *,
        dry_run: bool = False,
        persona_filter: str | None = None,
        scenario_filter: str | None = None,
        adversarial_filter: str | None = None,
        max_concurrency_override: int | None = None,
        run_id_override: str | None = None,
        realtime_chat: bool = False,
        output_conversations: bool = False,
        interactive_realtime_controls: bool = False,
) -> dict[str, Any]:
    persona_filter = _resolve_persona_filter(contract, persona_filter)
    run_id = run_id_override or contract.output.run_id or f"unified_run_{int(time.time())}"
    writer = UnifiedArtifactWriter(contract.output.base_dir, run_id=run_id)

    # Build LLM clients for each component (mock when dry_run regardless of contract.llm.provider).
    if dry_run:
        contract = _force_mock_providers(contract)
    llms = build_component_llms(contract)

    # Shared resources (built BEFORE target so the meter can hook into the target client).
    token_budget = TokenBudgetManager(max_total_tokens=contract.run.budget)
    meter = BudgetMeter(budget=token_budget)
    # Pre-register every component so the per_component breakdown is present even
    # if no calls were made (e.g. dry-run with zero adversarial turns).
    for component in ("planner", "generator", "judge", "policy", "user_simulator"):
        meter.register(component, llms[component].spec.model or "unknown")
    if contract.target.mode == "llm" and contract.target_llm is not None:
        meter.register("target_bot", contract.target_llm.model or "unknown")

    # Build target client. ASE chatbot factory handles api/browser/mock; we own "llm".
    if contract.target.mode == "llm":
        if contract.target_llm is None:
            raise RuntimeError(
                "target.mode == 'llm' but target_llm is None — contract loader should reject this earlier."
            )
        target = LLMTargetClient(
            contract.target_llm,
            contract.target_system_prompt,
            dry_run=dry_run,
            meter=meter,
            retry_max_attempts=contract.run.retry_max_attempts,
            retry_initial_backoff=contract.run.retry_initial_backoff_seconds,
            retry_max_backoff=contract.run.retry_max_backoff_seconds,
        )
    else:
        target = create_chatbot_client(
            contract.target,
            dry_run=dry_run,
            max_concurrency=max_concurrency_override or _effective_max_concurrency(contract),
        )

    attack_memory = (
        AttackMemory() if contract.eval_plan.attack_memory in {"shared"} else None
    )
    attack_memory_lock = asyncio.Lock()

    # Plan conversations.
    # - Cap mode (default): build a finite, weighted, deterministic plan list.
    # - Budget mode: lazy generator that draws an entry by weight each iteration
    #   so weights are honored even when the budget runs out before the safety cap.
    # Auto-enable budget mode when the contract omits total_conversations.
    budget_mode = (
            contract.run.until_budget_exhausted
            or contract.eval_plan.total_conversations is None
    )
    sequential = budget_mode
    if budget_mode:
        plan = list(_lazy_weighted_plan(contract, persona_filter, scenario_filter, adversarial_filter))
    else:
        plan = _build_plan(
            contract,
            persona_filter=persona_filter,
            scenario_filter=scenario_filter,
            adversarial_filter=adversarial_filter,
            unlimited=False,
        )

    if realtime_chat and persona_filter and plan:
        # Interactive persona-filtered realtime runs should represent exactly one live chat.
        plan = [plan[0]]
    elif realtime_chat and plan:
        plan = _round_robin_plan_by_persona(
            plan,
            [p.persona_id for p in contract.persona_pool],
        )

    for idx, planned in enumerate(plan, start=1):
        planned["conversation_id"] = f"conv_{idx:06d}"

    effective_max_concurrency = (
        1 if sequential
        else (max_concurrency_override or _effective_max_concurrency(contract))
    )
    if realtime_chat and persona_filter:
        effective_max_concurrency = 1
    semaphore = asyncio.Semaphore(max(1, effective_max_concurrency))

    # Build interactive realtime controller if requested.
    realtime_controller: RealtimeChatController | None = None
    if realtime_chat and interactive_realtime_controls:
        personas_dict = contract.persona_by_id()
        single_persona_mode = (len(personas_dict) <= 1) or (persona_filter is not None)
        persona_total_convos: dict[str, int] = {}
        for p in plan:
            persona_total_convos[p["persona_id"]] = persona_total_convos.get(p["persona_id"], 0) + 1
        realtime_controller = RealtimeChatController(
            personas=personas_dict,
            single_persona_mode=single_persona_mode,
            persona_total_convos=persona_total_convos,
        )
        for planned in plan[: max(1, effective_max_concurrency)]:
            realtime_controller.register_conversation_session(
                planned["conversation_id"],
                planned["persona_id"],
                total_turns=planned["turn_count"],
            )
        if persona_filter:
            realtime_controller.set_active_persona(persona_filter)
        elif contract.persona_pool:
            realtime_controller.set_active_persona(contract.persona_pool[0].persona_id)
        realtime_controller.start()

    async def _one(planned):
        async with semaphore:
            if realtime_controller:
                realtime_controller.register_conversation_session(
                    planned["conversation_id"],
                    planned["persona_id"],
                    total_turns=planned["turn_count"],
                )
            started = time.perf_counter()
            try:
                return await run_conversation(
                    entry=planned["entry"],
                    persona=contract.persona_by_id()[planned["persona_id"]],
                    synth_scenario=contract.scenario_by_id()[planned["synth_scenario_id"]],
                    adv_scenario=contract.adversarial_by_id()[planned["adversarial_scenario_id"]],
                    contract=contract,
                    llms=llms,
                    target=target,
                    writer=writer,
                    conversation_id=planned["conversation_id"],
                    rng=make_conversation_rng(contract.run.random_seed, planned["conversation_key"]),
                    token_budget=token_budget,
                    attack_memory=attack_memory,
                    attack_memory_lock=attack_memory_lock,
                    turn_count=planned["turn_count"],
                    realtime_chat=realtime_chat,
                    realtime_controller=realtime_controller,
                    meter=meter,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Conversation failed and will be recorded as an error: %s (%s)",
                    planned["conversation_id"],
                    type(exc).__name__,
                )
                return _failed_conversation_result(
                    planned=planned,
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=round(time.perf_counter() - started, 2),
                )

    budget_stopped = False
    start_time = time.time()
    try:
        if sequential:
            results: list[ConversationResult] = []
            for planned in plan:
                if realtime_controller and realtime_controller.stop_requested:
                    budget_stopped = True
                    break
                if not token_budget.can_continue(contract.run.reserve_tokens):
                    budget_stopped = True
                    break
                results.append(await _one(planned))
        else:
            results = await asyncio.gather(*(_one(p) for p in plan))
            # Concurrent mode: budget can't short-circuit mid-batch, but post-hoc flag it.
            budget_stopped = not token_budget.can_continue(contract.run.reserve_tokens)
    finally:
        if realtime_controller:
            realtime_controller.stop()
        close_async = getattr(target, "close_async", None)
        close_sync = getattr(target, "close", None)
        if close_async is not None:
            await close_async()
        elif callable(close_sync):
            await asyncio.to_thread(close_sync)

    elapsed_seconds = round(time.time() - start_time, 2)

    summary = _persist_and_summarize(
        contract=contract,
        writer=writer,
        results=results,
        plan=plan,
        run_id=run_id,
        dry_run=dry_run,
        attack_memory=attack_memory,
        output_conversations=output_conversations,
        meter=meter,
        budget_stopped=budget_stopped,
        elapsed_seconds=elapsed_seconds,
        effective_max_concurrency=effective_max_concurrency,
    )
    return summary


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _resolve_persona_filter(
        contract: UnifiedContract,
        persona_filter: str | None,
) -> str | None:
    """Resolve persona_filter to canonical persona_id (case-insensitive)."""
    if not persona_filter:
        return None

    personas_by_lower = {p.persona_id.lower(): p.persona_id for p in contract.persona_pool}
    matched = personas_by_lower.get(persona_filter.lower())
    if matched is None:
        raise ContractError(
            f"Specified persona '{persona_filter}' not found in contract's persona pool: "
            f"{[p.persona_id for p in contract.persona_pool]}"
        )
    return matched


def _lazy_weighted_plan(
        contract: UnifiedContract,
        persona_filter: str | None,
        scenario_filter: str | None,
        adversarial_filter: str | None,
):
    """Yield plan rows by per-iteration weighted draw.

    Used when until_budget_exhausted=true so weights are respected even if budget
    runs out before the safety cap. Capped at run.max_conversations_safety_cap.
    """
    entries = list(contract.eval_plan.entries)
    if persona_filter:
        entries = [e for e in entries if e.persona_id == persona_filter]
    if scenario_filter:
        entries = [e for e in entries if e.synth_scenario_id == scenario_filter]
    if adversarial_filter:
        entries = [e for e in entries if e.adversarial_scenario_id == adversarial_filter]
    if not entries:
        return

    weights = [max(0.0, e.weight) for e in entries]
    rng = random.Random(contract.run.random_seed or 0)
    turn_min = contract.eval_plan.conversation_turns.min
    turn_max = contract.eval_plan.conversation_turns.max
    safety_cap = contract.run.max_conversations_safety_cap

    for k in range(safety_cap):
        entry = rng.choices(entries, weights=weights, k=1)[0]
        turn_count = entry.max_turns or rng.randint(turn_min, turn_max)
        yield {
            "entry": entry,
            "persona_id": entry.persona_id,
            "synth_scenario_id": entry.synth_scenario_id,
            "adversarial_scenario_id": entry.adversarial_scenario_id,
            "turn_count": int(turn_count),
            "conversation_key": f"weighted_{k}:{entry.persona_id}:{entry.synth_scenario_id}:{entry.adversarial_scenario_id}",
        }


def _build_plan(
        contract: UnifiedContract,
        *,
        persona_filter: str | None,
        scenario_filter: str | None,
        adversarial_filter: str | None,
        unlimited: bool = False,
) -> list[dict[str, Any]]:
    entries = list(contract.eval_plan.entries)
    if persona_filter:
        entries = [e for e in entries if e.persona_id == persona_filter]
    if scenario_filter:
        entries = [e for e in entries if e.synth_scenario_id == scenario_filter]
    if adversarial_filter:
        entries = [e for e in entries if e.adversarial_scenario_id == adversarial_filter]
    if not entries:
        return []

    total = (
        contract.run.max_conversations_safety_cap
        if unlimited or contract.eval_plan.total_conversations is None
        else contract.eval_plan.total_conversations
    )
    weights = [max(0.0, e.weight) for e in entries]
    total_weight = sum(weights) or 1.0

    # Weighted allocation, rounding down then distributing remainders by largest fractional part.
    raw = [(total * w / total_weight) for w in weights]
    counts = [int(x) for x in raw]
    leftovers = total - sum(counts)
    fractional = sorted(
        range(len(entries)), key=lambda i: raw[i] - counts[i], reverse=True,
    )
    for i in fractional[:leftovers]:
        counts[i] += 1

    rng = random.Random(contract.run.random_seed or 0)
    turn_min = contract.eval_plan.conversation_turns.min
    turn_max = contract.eval_plan.conversation_turns.max

    plan: list[dict[str, Any]] = []
    for entry, count in zip(entries, counts):
        for k in range(count):
            turn_count = entry.max_turns or rng.randint(turn_min, turn_max)
            plan.append({
                "entry": entry,
                "persona_id": entry.persona_id,
                "synth_scenario_id": entry.synth_scenario_id,
                "adversarial_scenario_id": entry.adversarial_scenario_id,
                "turn_count": int(turn_count),
                "conversation_key": f"{entry.persona_id}:{entry.synth_scenario_id}:{entry.adversarial_scenario_id}:{k}",
            })
    return plan


def _round_robin_plan_by_persona(
        plan: list[dict[str, Any]],
        persona_order: list[str],
) -> list[dict[str, Any]]:
    """Interleave conversations by persona while preserving per-persona order.

    This keeps realtime active-session windows balanced across personas instead of
    clustering on the highest-weight persona at startup.
    """
    if len(plan) <= 1:
        return plan

    buckets: dict[str, deque[dict[str, Any]]] = {}
    for item in plan:
        pid = item.get("persona_id")
        buckets.setdefault(pid, deque()).append(item)

    ordered_personas = [pid for pid in persona_order if pid in buckets]
    for pid in buckets:
        if pid not in ordered_personas:
            ordered_personas.append(pid)

    interleaved: list[dict[str, Any]] = []
    while True:
        progressed = False
        for pid in ordered_personas:
            q = buckets.get(pid)
            if q:
                interleaved.append(q.popleft())
                progressed = True
        if not progressed:
            break
    return interleaved


def _effective_max_concurrency(contract: UnifiedContract) -> int:
    if contract.target.mode == "browser":
        return 1
    return max(1, int(contract.run.max_concurrency or 1))


def _failed_conversation_result(
        *,
        planned: dict[str, Any],
        error: str,
        elapsed_seconds: float,
) -> ConversationResult:
    conv_id = planned["conversation_id"]
    return ConversationResult(
        conversation_row={
            "conversation_id": conv_id,
            "session_id": conv_id,
            "persona_id": planned["persona_id"],
            "scenario_id": planned["synth_scenario_id"],
            "adversarial_scenario_id": planned["adversarial_scenario_id"],
            "synthetic_day": "",
            "turn_count": 0,
            "synth_turns": 0,
            "adversarial_turns": 0,
            "elapsed_seconds": elapsed_seconds,
            "target_latency_seconds": 0.0,
            "best_failure_score": 0,
        },
        chat_history=[],
        turn_rows=[
            {
                "conversation_id": conv_id,
                "turn_id": 0,
                "turn_type": "system_error",
                "error": error,
                "failure_mode": "runner_exception",
            }
        ],
        score_rows=[],
        failed_rows=[],
        adversarial_session=None,
        errors=1,
    )


def _force_mock_providers(contract: UnifiedContract) -> UnifiedContract:
    """For --dry-run: replace top-level llm with mock; clear per-component overrides.
    Target LLM (if any) is also mocked so no API key is required.
    """
    from adaptive_synth_eval.unified_eval.config.schemas import (
        ComponentOverrides,
        LLMSpec,
        UnifiedContract as _UC,
    )
    mock_spec = LLMSpec(provider="mock", model="mock", max_tokens=contract.llm.max_tokens)
    return _UC(
        suite=contract.suite,
        run=contract.run,
        llm=mock_spec,
        components=ComponentOverrides(),
        target=contract.target,
        time_window=contract.time_window,
        persona_pool=contract.persona_pool,
        scenario_catalog=contract.scenario_catalog,
        adversarial_scenario_catalog=contract.adversarial_scenario_catalog,
        eval_plan=contract.eval_plan,
        scoring=contract.scoring,
        output=contract.output,
        target_llm=(LLMSpec(provider="mock", model="mock") if contract.target_llm else None),
        target_system_prompt=contract.target_system_prompt,
        warnings=list(contract.warnings) + ["dry_run: forced mock LLM providers"],
    )


def _persist_and_summarize(
        *,
        contract: UnifiedContract,
        writer: UnifiedArtifactWriter,
        results: list[ConversationResult],
        plan: list[dict[str, Any]],
        run_id: str,
        dry_run: bool,
        attack_memory: AttackMemory | None,
        output_conversations: bool = False,
        meter: BudgetMeter | None = None,
        budget_stopped: bool = False,
        elapsed_seconds: float = 0.0,
        effective_max_concurrency: int = 1,
) -> dict[str, Any]:
    conv_rows = [r.conversation_row for r in results]
    chat_history = [rec for r in results for rec in r.chat_history]
    turn_rows = [row for r in results for row in r.turn_rows]
    score_rows = [row for r in results for row in r.score_rows]
    failed_rows = [row for r in results for row in r.failed_rows]
    adv_sessions = [r.adversarial_session for r in results if r.adversarial_session]
    errors = sum(r.errors for r in results)

    synth_turns = sum(r.conversation_row["synth_turns"] for r in results)
    adv_turns = sum(r.conversation_row["adversarial_turns"] for r in results)
    max_failure = max((r.conversation_row["best_failure_score"] for r in results), default=0)
    failures_at_threshold = sum(
        1 for r in results
        if r.conversation_row["best_failure_score"] >= contract.scoring.adversarial_failure_threshold
    )
    near_misses = sum(
        1 for row in turn_rows if row.get("turn_type") == "adversarial" and (
                row.get("failure_score") and 0 < row["failure_score"] < contract.scoring.adversarial_failure_threshold
        )
    )

    # Failure percentiles (p50/p90/p95) — surface "how close" attacks got, not just the binary count.
    threshold = contract.scoring.adversarial_failure_threshold
    failure_scores = [
        row["failure_score"]
        for row in score_rows
        if row.get("turn_type") == "adversarial" and isinstance(row.get("failure_score"), (int, float))
    ]
    turns_to_failure = [
        r.conversation_row["adversarial_turns"]
        for r in results
        if r.conversation_row["best_failure_score"] >= threshold
    ]
    failure_percentiles = {
        "failure_score": _percentiles(failure_scores),
        "turns_to_failure": _percentiles(turns_to_failure),
    }

    synth_score_rows = [row for row in score_rows if row.get("turn_type") == "synth"]
    mean_safety = _mean([row.get("safety_score") for row in synth_score_rows])
    mean_relevance = _mean([row.get("relevance_score") for row in synth_score_rows])
    mean_grounded = _mean([row.get("groundedness_score") for row in synth_score_rows])

    writer.write_json("contract.normalized.json", contract_to_dict(contract))
    writer.write_json("run_plan.json", _serialize_plan(plan))
    writer.write_chat_history(chat_history)
    writer.write_jsonl("conversations.jsonl", conv_rows)
    writer.write_jsonl("turns.jsonl", turn_rows)
    writer.write_jsonl("scores.jsonl", score_rows)
    writer.write_failed_examples(failed_rows)
    writer.write_adversarial_sessions(adv_sessions)
    if attack_memory is not None:
        writer.write_attack_memory({
            "entries": [asdict(e) for e in attack_memory.entries],
            "max_entries": attack_memory.max_entries,
        })

    budget_summary = (
        meter.summary(stopped_due_to_budget=budget_stopped) if meter is not None else None
    )

    # Calculate token usage statistics from meter (simulator tokens only)
    simulator_prompt_tokens = 0
    simulator_completion_tokens = 0
    if meter is not None:
        sim_meter = meter.components.get("user_simulator")
        if sim_meter is not None:
            simulator_prompt_tokens = sim_meter.prompt_tokens
            simulator_completion_tokens = sim_meter.completion_tokens
    simulator_total_tokens = simulator_prompt_tokens + simulator_completion_tokens

    avg_prompt_tokens_convo = round(simulator_prompt_tokens / len(results), 2) if results else 0.0
    avg_completion_tokens_convo = round(simulator_completion_tokens / len(results), 2) if results else 0.0
    avg_total_tokens_convo = round(simulator_total_tokens / len(results), 2) if results else 0.0

    # Calculate estimated chatbot token usage
    chatbot_prompt_tokens = sum(
        rec.generation_metadata.get("chatbot_prompt_tokens", 0)
        for rec in chat_history
        if rec.generation_metadata
    )
    chatbot_completion_tokens = sum(
        rec.generation_metadata.get("chatbot_completion_tokens", 0)
        for rec in chat_history
        if rec.generation_metadata
    )
    chatbot_total_tokens = chatbot_prompt_tokens + chatbot_completion_tokens

    avg_chatbot_prompt_tokens_convo = round(chatbot_prompt_tokens / len(results), 2) if results else 0.0
    avg_chatbot_completion_tokens_convo = round(chatbot_completion_tokens / len(results), 2) if results else 0.0
    avg_chatbot_total_tokens_convo = round(chatbot_total_tokens / len(results), 2) if results else 0.0

    tokens_stats = {
        "simulator_prompt_tokens": simulator_prompt_tokens,
        "simulator_completion_tokens": simulator_completion_tokens,
        "simulator_total_tokens": simulator_total_tokens,
        "avg_prompt_tokens_per_convo": avg_prompt_tokens_convo,
        "avg_completion_tokens_per_convo": avg_completion_tokens_convo,
        "avg_total_tokens_per_convo": avg_total_tokens_convo,
        "chatbot_prompt_tokens": chatbot_prompt_tokens,
        "chatbot_completion_tokens": chatbot_completion_tokens,
        "chatbot_total_tokens": chatbot_total_tokens,
        "avg_chatbot_prompt_tokens_per_convo": avg_chatbot_prompt_tokens_convo,
        "avg_chatbot_completion_tokens_per_convo": avg_chatbot_completion_tokens_convo,
        "avg_chatbot_total_tokens_per_convo": avg_chatbot_total_tokens_convo,
    }

    target_latencies_ms = [
        row.get("latency_ms")
        for row in turn_rows
        if isinstance(row.get("latency_ms"), (int, float))
    ]
    conversation_elapsed_seconds = [
        row.get("elapsed_seconds")
        for row in conv_rows
        if isinstance(row.get("elapsed_seconds"), (int, float))
    ]
    conversation_target_seconds = [
        row.get("target_latency_seconds")
        for row in conv_rows
        if isinstance(row.get("target_latency_seconds"), (int, float))
    ]
    performance_stats = {
        "target_latency_total_seconds": round(sum(target_latencies_ms) / 1000, 2) if target_latencies_ms else 0.0,
        "avg_target_latency_per_turn_seconds": round(sum(target_latencies_ms) / len(target_latencies_ms) / 1000, 2)
        if target_latencies_ms else 0.0,
        "max_target_latency_per_turn_seconds": round(max(target_latencies_ms) / 1000,
                                                     2) if target_latencies_ms else 0.0,
        "avg_conversation_elapsed_seconds": round(sum(conversation_elapsed_seconds) / len(conversation_elapsed_seconds),
                                                  2)
        if conversation_elapsed_seconds else 0.0,
        "max_conversation_elapsed_seconds": round(max(conversation_elapsed_seconds), 2)
        if conversation_elapsed_seconds else 0.0,
        "avg_target_latency_per_conversation_seconds": round(
            sum(conversation_target_seconds) / len(conversation_target_seconds), 2
        ) if conversation_target_seconds else 0.0,
    }

    # Scale Projections
    convo_count = len(results)
    rate = convo_count / elapsed_seconds if elapsed_seconds > 0 else 0.0
    time_1k = round(1000 / rate, 2) if rate > 0 else 0.0
    time_10k = round(10000 / rate, 2) if rate > 0 else 0.0
    time_100k = round(100000 / rate, 2) if rate > 0 else 0.0

    scale_projections = {
        "conversations_per_second": round(rate, 4),
        "time_for_1k_conversations_seconds": time_1k,
        "time_for_10k_conversations_seconds": time_10k,
        "time_for_100k_conversations_seconds": time_100k,
    }
    avg_conversation_elapsed = performance_stats["avg_conversation_elapsed_seconds"]
    if avg_conversation_elapsed > 0:
        steady_rate = max(1, int(effective_max_concurrency)) / avg_conversation_elapsed
        scale_projections.update({
            "steady_state_conversations_per_second": round(steady_rate, 4),
            "steady_state_time_for_1k_conversations_seconds": round(1000 / steady_rate, 2),
            "steady_state_time_for_10k_conversations_seconds": round(10000 / steady_rate, 2),
            "steady_state_time_for_100k_conversations_seconds": round(100000 / steady_rate, 2),
        })

    summary = {
        "run_id": run_id,
        "total_conversations": len(results),
        "total_turns": len(turn_rows),
        "synth_turns": synth_turns,
        "adversarial_turns": adv_turns,
        "errors": errors,
        "dry_run": dry_run,
        "elapsed_seconds": elapsed_seconds,
        "output_dir": str(writer.run_dir),
        "configured_max_concurrency": int(contract.run.max_concurrency or 1),
        "effective_max_concurrency": int(max(1, effective_max_concurrency)),
        "max_failure_score": max_failure,
        "failures_at_threshold": failures_at_threshold,
        "near_misses": near_misses,
        "failure_percentiles": failure_percentiles,
        "mean_safety_score": mean_safety,
        "mean_relevance_score": mean_relevance,
        "mean_groundedness_score": mean_grounded,
        "budget": budget_summary,
        "tokens": tokens_stats,
        "performance": performance_stats,
        "scale_projections": scale_projections,
    }
    writer.write_unified_summary(summary)
    writer.write_unified_report(summary)
    if output_conversations:
        writer.write_conversations_txt(chat_history)
    return summary


def _mean(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _percentile(values, q):
    """Nearest-rank percentile. q in [0, 100]. Returns None for empty input."""
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    if not nums:
        return None
    if len(nums) == 1:
        return round(float(nums[0]), 4)
    rank = math.ceil((q / 100.0) * len(nums))
    idx = min(max(rank, 1), len(nums)) - 1
    return round(float(nums[idx]), 4)


def _percentiles(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    return {
        "p50": _percentile(nums, 50),
        "p90": _percentile(nums, 90),
        "p95": _percentile(nums, 95),
        "count": len(nums),
    }


def _serialize_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for p in plan:
        rows.append({
            "persona_id": p["persona_id"],
            "synth_scenario_id": p["synth_scenario_id"],
            "adversarial_scenario_id": p["adversarial_scenario_id"],
            "turn_count": p["turn_count"],
            "conversation_key": p["conversation_key"],
            "weight": p["entry"].weight,
            "synth_to_adversarial_ratio": p["entry"].synth_to_adversarial_ratio,
        })
    return rows
