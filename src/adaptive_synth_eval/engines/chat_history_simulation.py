from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.artifacts.schemas import ChatHistoryRecord
from adaptive_synth_eval.clients.chatbot import ChatbotClient
from adaptive_synth_eval.config.contract import contract_to_dict
from adaptive_synth_eval.config.schemas import SimulationContract
from adaptive_synth_eval.generation.traffic import build_run_plan
from adaptive_synth_eval.generation.turns import UserSimulator
from adaptive_synth_eval.scoring.failure_modes import detect_failure_mode
from adaptive_synth_eval.scoring.response_quality import score_response


def run_simulation(contract: SimulationContract, *, dry_run: bool = False) -> dict:
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

    def process_conversation(planned):
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
            "turn_count": planned.turn_count,
        }

        previous_bot_response = None
        for turn_id in range(1, planned.turn_count + 1):
            turn = simulator.generate_turn(turn_id, previous_bot_response)
            response = client.send(
                conversation_id=planned.conversation_id,
                session_id=planned.session_id,
                turn_id=turn.turn_id,
                user_message=turn.user_message,
                metadata={"persona_id": planned.persona_id, "scenario_id": planned.scenario_id, "synthetic": True},
            )
            if response.error:
                local_errors += 1
            previous_bot_response = response.bot_response
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

        return local_conversation_row, local_records, local_turn_rows, local_score_rows, local_errors

    with ThreadPoolExecutor(max_workers=10) as executor:
        for conv_row, loc_recs, loc_turn_rows, loc_score_rows, loc_errs in executor.map(process_conversation, plan):
            conversation_rows.append(conv_row)
            records.extend(loc_recs)
            turn_rows.extend(loc_turn_rows)
            score_rows.extend(loc_score_rows)
            errors += loc_errs

    summary = {
        "run_id": run_id,
        "total_conversations": len(plan),
        "total_turns": len(records),
        "errors": errors,
        "dry_run": dry_run,
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
    return summary
