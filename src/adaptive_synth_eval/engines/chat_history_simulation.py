from __future__ import annotations

import asyncio
import time

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.artifacts.schemas import ChatHistoryRecord
from adaptive_synth_eval.clients.chatbot import ChatbotClient
from adaptive_synth_eval.clients.utils import stream_simulated_chat_turn
from adaptive_synth_eval.config.contract import contract_to_dict
from adaptive_synth_eval.config.schemas import SimulationContract
from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController
from adaptive_synth_eval.generation.traffic import build_run_plan
from adaptive_synth_eval.generation.turns import UserSimulator
from adaptive_synth_eval.scoring.failure_modes import detect_failure_mode
from adaptive_synth_eval.scoring.response_quality import score_response


def run_simulation(
        contract: SimulationContract,
        *,
        dry_run: bool = False,
        output_conversations: bool = False,
        realtime_chat: bool = False,
        interactive_realtime_controls: bool = False,
) -> dict:
    """Synchronously run the async simulation pipeline for CLI/backwards compatibility."""
    return asyncio.run(
        run_simulation_async(
            contract,
            dry_run=dry_run,
            output_conversations=output_conversations,
            realtime_chat=realtime_chat,
            interactive_realtime_controls=interactive_realtime_controls,
        )
    )


async def run_simulation_async(
        contract: SimulationContract,
        *,
        dry_run: bool = False,
        output_conversations: bool = False,
        realtime_chat: bool = False,
        interactive_realtime_controls: bool = False,
) -> dict:
    run_id = contract.output.run_id or f"run_{int(time.time())}"
    writer = ArtifactWriter(contract.output.base_dir, run_id=run_id)
    plan = build_run_plan(contract.traffic, contract.time_window)
    personas = contract.persona_by_id()
    scenarios = contract.scenario_by_id()
    client = ChatbotClient(
        endpoint=contract.target_chatbot.endpoint,
        enabled=contract.target_chatbot.enabled and not dry_run,
        auth=contract.target_chatbot.auth,
        timeout_seconds=contract.target_chatbot.timeout_seconds,
    )

    records: list[ChatHistoryRecord] = []
    conversation_rows = []
    turn_rows = []
    score_rows = []
    errors = 0
    realtime_chat_enabled = realtime_chat and len(contract.persona_pool) == 1
    stopped_early = False
    realtime_controller: RealtimeChatController | None = None

    if realtime_chat and not realtime_chat_enabled:
        print("Realtime chat display is only enabled when persona_pool has exactly one persona; skipping live output.")
    if interactive_realtime_controls and not realtime_chat:
        print("Interactive realtime controls require --realtime-chat; skipping controls.")
    if interactive_realtime_controls and realtime_chat and not realtime_chat_enabled:
        print("Interactive realtime controls were requested, but realtime chat is disabled for multi-persona runs.")

    if realtime_chat_enabled and interactive_realtime_controls:
        realtime_controller = RealtimeChatController()
        realtime_controller.start()

    async def process_conversation(planned):
        local_records = []
        local_turn_rows = []
        local_score_rows = []
        local_errors = 0

        persona = personas[planned.persona_id]
        scenario = scenarios[planned.scenario_id]
        simulator = UserSimulator(persona, scenario, turn_count=planned.turn_count,
                                  seed=hash(planned.conversation_id) % 10_000)

        local_conversation_row = {
            "conversation_id": planned.conversation_id,
            "session_id": planned.session_id,
            "persona_id": planned.persona_id,
            "scenario_id": planned.scenario_id,
            "synthetic_day": planned.synthetic_day.isoformat(),
            "turn_count": 0,
        }

        previous_bot_response = None
        for turn_id in range(1, planned.turn_count + 1):
            if realtime_controller and realtime_controller.stop_requested:
                break
            if realtime_controller and not await asyncio.to_thread(realtime_controller.wait_if_paused):
                break

            behavior_override = realtime_controller.behavior_mode if realtime_controller else None
            turn = await simulator.generate_turn_async(
                turn_id,
                previous_bot_response,
                behavior_override=behavior_override,
            )
            response = await client.send_async(
                conversation_id=planned.conversation_id,
                session_id=planned.session_id,
                turn_id=turn.turn_id,
                user_message=turn.user_message,
                metadata={"persona_id": planned.persona_id, "scenario_id": planned.scenario_id, "synthetic": True},
            )
            if response.error:
                local_errors += 1
            previous_bot_response = response.bot_response

            if realtime_chat_enabled:
                await asyncio.to_thread(
                    stream_simulated_chat_turn,
                    conversation_id=planned.conversation_id,
                    persona_id=planned.persona_id,
                    scenario_id=planned.scenario_id,
                    turn_id=turn.turn_id,
                    human_message=turn.user_message,
                    bot_message=response.bot_response,
                )

            score = score_response(
                user_message=turn.user_message,
                bot_response=response.bot_response,
                expected_context=scenario.context,
                missing_context_expected="missing_information" in turn.applied_failure_modes,
            )
            failure_mode = detect_failure_mode(response.bot_response, response.error, score.safety_score)
            record = ChatHistoryRecord(
                conversation_id=planned.conversation_id,
                session_id=planned.session_id,
                synthetic_day=planned.synthetic_day,
                persona_id=planned.persona_id,
                scenario_id=planned.scenario_id,
                turn_id=turn.turn_id,
                user_message=turn.user_message,
                bot_response=response.bot_response,
                expected_retrieval_topics=scenario.expected_retrieval_topics,
                planned_failure_modes=turn.planned_failure_modes,
                applied_failure_modes=turn.applied_failure_modes,
                groundedness_score=score.groundedness_score,
                relevance_score=score.relevance_score,
                safety_score=score.safety_score,
                clarification_score=score.clarification_score,
                failure_mode=failure_mode,
                latency_ms=response.latency_ms,
                error=response.error,
                synthetic_flag=contract.synthetic_flag,
                retrieved_policy_ids=response.retrieved_policy_ids,
                response_raw=response.raw,
                generation_metadata=turn.generation_metadata,
            )
            local_records.append(record)
            local_turn_rows.append(record.to_dict())
            local_conversation_row["turn_count"] += 1
            local_score_rows.append(
                {
                    "conversation_id": planned.conversation_id,
                    "turn_id": turn.turn_id,
                    "groundedness_score": score.groundedness_score,
                    "relevance_score": score.relevance_score,
                    "safety_score": score.safety_score,
                    "clarification_score": score.clarification_score,
                    "failure_mode": failure_mode,
                }
            )

            if realtime_controller and not await asyncio.to_thread(realtime_controller.wait_for_turn_delay):
                break

        return local_conversation_row, local_records, local_turn_rows, local_score_rows, local_errors

    try:
        if realtime_chat_enabled:
            # Keep live transcript ordering stable for single-persona runs.
            for planned in plan:
                conv_row, loc_recs, loc_turn_rows, loc_score_rows, loc_errs = await process_conversation(planned)
                conversation_rows.append(conv_row)
                records.extend(loc_recs)
                turn_rows.extend(loc_turn_rows)
                score_rows.extend(loc_score_rows)
                errors += loc_errs

                if realtime_controller and realtime_controller.stop_requested:
                    stopped_early = True
                    break
        else:
            max_concurrency = max(1, int(getattr(contract.traffic, "max_concurrency", 5) or 5))
            semaphore = asyncio.Semaphore(max_concurrency)

            async def limited_process(planned):
                async with semaphore:
                    return await process_conversation(planned)

            results = await asyncio.gather(*(limited_process(planned) for planned in plan))
            for conv_row, loc_recs, loc_turn_rows, loc_score_rows, loc_errs in results:
                conversation_rows.append(conv_row)
                records.extend(loc_recs)
                turn_rows.extend(loc_turn_rows)
                score_rows.extend(loc_score_rows)
                errors += loc_errs
    finally:
        if realtime_controller:
            realtime_controller.stop()

    summary = {
        "run_id": run_id,
        "total_conversations": len(plan),
        "total_turns": len(records),
        "errors": errors,
        "dry_run": dry_run,
        "stopped_early": stopped_early,
        "output_dir": str(writer.run_dir),
    }
    writer.write_json("contract.normalized.json", contract_to_dict(contract))
    writer.write_json("run_plan.json", [item.__dict__ for item in plan])
    writer.write_chat_history(records)
    writer.write_jsonl("conversations.jsonl", conversation_rows)
    writer.write_jsonl("turns.jsonl", turn_rows)
    writer.write_jsonl("scores.jsonl", score_rows)
    writer.write_json("run_summary.json", summary)
    writer.write_generation_report(summary)

    if output_conversations:
        writer.write_conversations_txt(records)

    return summary
