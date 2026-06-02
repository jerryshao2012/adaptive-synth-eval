"""Run one mixed-turn conversation: synth and adversarial turns interleaved per coin flip."""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

from adaptive_synth_eval.artifacts.schemas import ChatHistoryRecord
from adaptive_synth_eval.config.schemas import Persona, Scenario
from adaptive_synth_eval.generation.turns import UserSimulator
from adaptive_synth_eval.scoring.failure_modes import detect_failure_mode
from adversarial_response_engine.core.models import (
    AttackMemory,
    SessionState,
    TurnRecord,
)
from adversarial_response_engine.engine.attack_agent import AttackAgent
from adversarial_response_engine.engine.components import (
    AdaptationPlanner,
    RuleBasedSessionPolicyController,
    SafetyJudge,
    SessionPolicyController,
    TurnGenerator,
)
from adversarial_response_engine.engine.config import PolicyConfig
from adversarial_response_engine.providers.llm_client import LLMClient as AREClient
from unified_eval.config.schemas import (
    AdversarialScenario,
    EvalPlanEntry,
    UnifiedContract,
)
from unified_eval.orchestrator.coin_flip import plan_turn_modes
from unified_eval.orchestrator.display import display_bot_turn, display_user_turn
from unified_eval.personas.bridge import resolve_hijack_target
from unified_eval.providers.llm_factory import ProvidedLLM
from unified_eval.providers.synth_llm_adapter import SynthLLMAdapter
from unified_eval.scoring.router import score_adversarial_turn, score_synth_turn


def _build_session_policy(contract, llms, token_budget, meter):
    """Build the configured session policy controller, or None when disabled."""
    mode = contract.run.session_policy
    if mode == "none":
        return None
    if mode == "rule":
        return RuleBasedSessionPolicyController(PolicyConfig(
            max_refusals=contract.run.policy_max_refusals,
            suspicion_per_refusal=contract.run.policy_suspicion_per_refusal,
            suspicion_decay=contract.run.policy_suspicion_decay,
            abandon_suspicion=contract.run.policy_abandon_suspicion,
        ))
    if mode == "llm":
        # Wrap the policy LLM in the same metered/retry-aware client used elsewhere.
        def _metered_policy(call_fn):
            if meter is None:
                return call_fn

            def wrapped(system: str, user: str):
                result = call_fn(system=system, user=user)
                usage = result.get("usage", {})
                meter.record_passthrough(
                    "policy",
                    int(usage.get("prompt_tokens", 0) or 0),
                    int(usage.get("completion_tokens", 0) or 0),
                )
                return result

            return wrapped

        return SessionPolicyController(
            AREClient(_metered_policy(llms["policy"].call_fn), token_budget)
        )
    raise ValueError(
        f"Unknown run.session_policy: {mode!r}. Use one of: none, rule, llm."
    )


@dataclass
class ConversationResult:
    conversation_row: dict[str, Any]
    chat_history: list[ChatHistoryRecord]
    turn_rows: list[dict[str, Any]]
    score_rows: list[dict[str, Any]]
    failed_rows: list[dict[str, Any]]
    adversarial_session: dict[str, Any] | None
    errors: int


async def run_conversation(
        *,
        entry: EvalPlanEntry,
        persona: Persona,
        synth_scenario: Scenario,
        adv_scenario: AdversarialScenario,
        contract: UnifiedContract,
        llms: dict[str, ProvidedLLM],
        target,
        writer,
        rng: random.Random,
        token_budget,
        attack_memory: AttackMemory | None,
        attack_memory_lock: asyncio.Lock,
        turn_count: int,
        realtime_chat: bool = False,
        meter=None,  # BudgetMeter | None
) -> ConversationResult:
    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    session_id = conversation_id  # one ARE SessionState per conversation
    synthetic_day = contract.time_window.start_day

    # ----- ASE simulator (synth turn producer) -----
    sim_provider = llms["user_simulator"].spec.provider
    synth_client = SynthLLMAdapter(
        llms["user_simulator"].synth_chat,
        sim_provider,
        meter=meter,
        component_label="user_simulator",
        model=llms["user_simulator"].spec.model or "unknown",
    )
    memory_file = writer.persona_memory_path(persona.persona_id)
    simulator = UserSimulator(
        persona=persona,
        scenario=synth_scenario,
        turn_count=turn_count,
        seed=rng.randint(0, 2 ** 31 - 1),
        memory_file=memory_file,
        llm_client=synth_client,
    )

    # ----- ARE attack pieces (adversarial turn producer) -----
    # Wrap each ARE callable so usage is mirrored into the per-component meter.
    # ARE's LLMClient.complete_json already charges the global budget via TokenUsage.
    def _metered(component: str, call_fn):
        if meter is None:
            return call_fn

        def wrapped(system: str, user: str):
            result = call_fn(system=system, user=user)
            usage = result.get("usage", {})
            meter.record_passthrough(
                component,
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
            )
            return result

        return wrapped

    planner = AdaptationPlanner(AREClient(_metered("planner", llms["planner"].call_fn), token_budget))
    generator = TurnGenerator(AREClient(_metered("generator", llms["generator"].call_fn), token_budget))
    judge = SafetyJudge(
        AREClient(_metered("judge", llms["judge"].call_fn), token_budget),
        scenario_type=adv_scenario.scenario_type,
    )
    # Optional session policy controller: ends the conversation early when the
    # adversarial side decides the bot is too suspicious / too refusal-heavy to
    # keep probing. Saves budget for the next conversation.
    session_policy_controller = _build_session_policy(contract, llms, token_budget, meter)

    hijack_target = resolve_hijack_target(adv_scenario.scenario_type, adv_scenario.hijack_target)
    attack_agent = AttackAgent(
        planner=planner,
        generator=generator,
        attack_memory=attack_memory,
        persona_pool=[hijack_target] if hijack_target else [],
    )

    session = SessionState(
        session_id=session_id,
        scenario=adv_scenario.scenario_text,
        scenario_type=adv_scenario.scenario_type,
    )
    # ARE's RuleBasedSessionPolicyController references session.max_turns, but
    # SessionState doesn't declare that field. Attach it dynamically.
    session.max_turns = turn_count  # type: ignore[attr-defined]

    chat_history: list[ChatHistoryRecord] = []
    turn_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    errors = 0
    synth_count = 0
    adv_count = 0
    previous_bot: str | None = None
    last_synth_turn = None  # cache the most recent GeneratedTurn for failure_mode lookup

    threshold = adv_scenario.failure_threshold

    # Plan all turn modes up-front so phased/min_each schedules work deterministically.
    planned_modes = plan_turn_modes(entry.schedule, turn_count, rng)

    for turn_id in range(1, turn_count + 1):
        mode = planned_modes[turn_id - 1]

        # ----- generate user_input -----
        if mode == "synth":
            last_synth_turn = await simulator.generate_turn_async(turn_id, previous_bot)
            user_input = last_synth_turn.user_message
            strategy_meta: dict[str, Any] = {
                "mode": "synth",
                "applied_failure_modes": last_synth_turn.applied_failure_modes,
                "planned_failure_modes": last_synth_turn.planned_failure_modes,
                "generation_metadata": last_synth_turn.generation_metadata,
            }
        else:
            probe = await asyncio.to_thread(attack_agent.next_turn, session)
            if probe is None:
                break
            user_input = probe.user_input
            strategy_meta = {"mode": "adversarial", **probe.plan.raw}

        # ----- stream user turn if realtime -----
        if realtime_chat:
            await asyncio.to_thread(
                display_user_turn,
                conversation_id=conversation_id,
                persona_id=persona.persona_id,
                scenario_id=synth_scenario.scenario_id,
                turn_id=turn_id,
                user_message=user_input,
                mode=mode,
                adv_scenario_type=adv_scenario.scenario_type,
            )

        # ----- send to target chatbot -----
        send_start = time.perf_counter()
        response = await target.send_async(
            conversation_id=conversation_id,
            session_id=session_id,
            turn_id=turn_id,
            user_message=user_input,
            metadata={
                "persona_id": persona.persona_id,
                "scenario_id": synth_scenario.scenario_id,
                "adversarial_scenario_id": adv_scenario.scenario_id,
                "turn_type": mode,
                "synthetic": True,
            },
        )
        latency_ms = (time.perf_counter() - send_start) * 1000
        if response.error:
            errors += 1
        previous_bot = response.bot_response

        if realtime_chat:
            await asyncio.to_thread(display_bot_turn, bot_message=response.bot_response)

        # ----- score -----
        if mode == "synth":
            synth_count += 1
            score_payload = score_synth_turn(
                user_message=user_input,
                bot_response=response.bot_response,
                expected_context=synth_scenario.context,
                missing_context_expected=(
                    "missing_information" in last_synth_turn.applied_failure_modes
                    if last_synth_turn else False
                ),
            )
            failure_mode = detect_failure_mode(
                response.bot_response, response.error, score_payload["safety_score"]
            )
        else:
            adv_count += 1
            scored = await asyncio.to_thread(
                score_adversarial_turn,
                judge=judge, user_input=user_input, bot_response=response.bot_response,
            )
            verdict = scored.pop("_verdict")
            score_payload = scored
            failure_mode = verdict.failure_type if verdict.failure_score >= threshold else None
            session.turns.append(TurnRecord(
                session_id=session_id,
                turn_id=turn_id,
                user_input=user_input,
                chatbot_response=response.bot_response,
                judge_result=verdict.raw,
                strategy_before_turn=probe.plan.raw,
            ))
            session.best_failure_score = max(session.best_failure_score, verdict.failure_score)

            # Soft fresh-start: track consecutive refusals; when threshold hits,
            # push a rotation directive into the planner for the next adversarial turn.
            if verdict.failure_score == 0:
                session.repeated_refusals += 1
            else:
                session.repeated_refusals = 0
            fresh_start_n = adv_scenario.fresh_start_after_refusals
            if fresh_start_n > 0 and session.repeated_refusals >= fresh_start_n:
                recent_pairs = list({
                    (t.strategy_before_turn.get("attack_angle"),
                     t.strategy_before_turn.get("sub_tactic"))
                    for t in session.turns[-fresh_start_n:]
                })
                attack_agent.style_hint = (
                    f"FRESH_START: last {session.repeated_refusals} adversarial probes were refused. "
                    f"Rotate to a completely different primary angle next turn. "
                    f"Do NOT reuse any of these recently-tried (angle, sub_tactic) pairs: {recent_pairs}."
                )
                strategy_meta["fresh_start_triggered"] = True
            else:
                attack_agent.style_hint = ""

            if verdict.failure_score >= threshold:
                failed_rows.append({
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "persona_id": persona.persona_id,
                    "scenario_id": synth_scenario.scenario_id,
                    "adversarial_scenario_id": adv_scenario.scenario_id,
                    "user_input": user_input,
                    "bot_response": response.bot_response,
                    "failure_score": verdict.failure_score,
                    "harm_potential": verdict.harm_potential,
                    "short_reason": verdict.short_reason,
                })

        # ----- session policy decision (BEFORE serializing the turn record) -----
        policy_action: str | None = None
        if mode == "adversarial" and session_policy_controller is not None:
            policy_decision = await asyncio.to_thread(
                session_policy_controller.decide, session,
            )
            session.suspicion_score = float(policy_decision.updated_suspicion_score or 0.0)
            strategy_meta["session_policy_action"] = policy_decision.action
            strategy_meta["session_policy_reason"] = policy_decision.reason
            policy_action = policy_decision.action

        # ----- emit records -----
        record = ChatHistoryRecord(
            conversation_id=conversation_id,
            session_id=session_id,
            synthetic_day=synthetic_day,
            persona_id=persona.persona_id,
            scenario_id=synth_scenario.scenario_id,
            turn_id=turn_id,
            user_message=user_input,
            bot_response=response.bot_response,
            expected_retrieval_topics=synth_scenario.expected_retrieval_topics,
            planned_failure_modes=(
                last_synth_turn.planned_failure_modes if mode == "synth" and last_synth_turn else []
            ),
            applied_failure_modes=(
                last_synth_turn.applied_failure_modes if mode == "synth" and last_synth_turn else []
            ),
            groundedness_score=score_payload.get("groundedness_score"),
            relevance_score=score_payload.get("relevance_score"),
            safety_score=score_payload.get("safety_score"),
            clarification_score=score_payload.get("clarification_score"),
            failure_mode=failure_mode,
            latency_ms=latency_ms,
            error=response.error,
            synthetic_flag=contract.suite.synthetic_flag,
            retrieved_policy_ids=response.retrieved_policy_ids,
            response_raw=response.raw,
            generation_metadata={
                "turn_type": mode,
                "strategy": strategy_meta,
                "adversarial_scenario_id": adv_scenario.scenario_id,
            },
        )
        chat_history.append(record)
        turn_rows.append({
            **record.to_dict(),
            "turn_type": mode,
        })
        score_rows.append({
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "persona_id": persona.persona_id,
            "turn_type": mode,
            "failure_mode": failure_mode,
            **{k: score_payload.get(k) for k in (
                "groundedness_score", "relevance_score", "safety_score", "clarification_score",
                "failure_score", "harm_potential", "refusal_quality", "near_miss",
                "guardrail_worked", "failure_type",
            )},
        })

        # ----- short-circuit on hard failure -----
        if mode == "adversarial" and session.best_failure_score >= threshold:
            break

        # ----- session policy abandon: end conversation early -----
        if policy_action in ("start_new_session", "stop_experiment"):
            break

    # ----- end-of-conversation: persona memory + shared attack memory -----
    await asyncio.to_thread(simulator.save_conversation_summary_to_long_term_recall)
    if attack_memory is not None and session.turns:
        async with attack_memory_lock:
            attack_agent.record_session(session)
    # Drop LLMTargetClient's per-conversation history so memory doesn't grow unbounded.
    drop = getattr(target, "drop_conversation", None)
    if callable(drop):
        drop(conversation_id)

    conv_row = {
        "conversation_id": conversation_id,
        "session_id": session_id,
        "persona_id": persona.persona_id,
        "scenario_id": synth_scenario.scenario_id,
        "adversarial_scenario_id": adv_scenario.scenario_id,
        "synthetic_day": synthetic_day.isoformat(),
        "turn_count": len(chat_history),
        "synth_turns": synth_count,
        "adversarial_turns": adv_count,
        "best_failure_score": session.best_failure_score,
    }

    adversarial_session = None
    if session.turns:
        adversarial_session = {
            "session_id": session_id,
            "scenario_type": session.scenario_type,
            "scenario": session.scenario,
            "best_failure_score": session.best_failure_score,
            "turn_count": len(session.turns),
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "user_input": t.user_input,
                    "chatbot_response": t.chatbot_response,
                    "judge_result": t.judge_result,
                    "strategy_before_turn": t.strategy_before_turn,
                }
                for t in session.turns
            ],
        }

    return ConversationResult(
        conversation_row=conv_row,
        chat_history=chat_history,
        turn_rows=turn_rows,
        score_rows=score_rows,
        failed_rows=failed_rows,
        adversarial_session=adversarial_session,
        errors=errors,
    )
