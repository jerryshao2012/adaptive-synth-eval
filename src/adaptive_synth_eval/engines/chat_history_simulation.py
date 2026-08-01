from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.artifacts.fingerprints import fingerprint_payload
from adaptive_synth_eval.artifacts.run_state import (
    load_run_state,
    now_iso,
    write_run_state,
)
from adaptive_synth_eval.artifacts.schemas import ChatHistoryRecord
from adaptive_synth_eval.capture.producers import ChatHistoryProducerAdapter
from adaptive_synth_eval.capture.runtime import capture_coordinator_from_env
from adaptive_synth_eval.clients.chatbot_factory import create_chatbot_client
from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.clients.utils import (
    count_tokens,
    display_bot_message,
    display_persona_message,
)
from adaptive_synth_eval.config.contract import ContractError, contract_to_dict
from adaptive_synth_eval.config.schemas import SimulationContract
from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController
from adaptive_synth_eval.generation.time_profile import (
    profile_provenance,
    profile_turn_provenance,
    resolve_behavior_override,
    summarize_profile_plan,
)
from adaptive_synth_eval.generation.traffic import (
    build_profiled_run_plan,
    build_run_plan,
)
from adaptive_synth_eval.generation.turns import UserSimulator
from adaptive_synth_eval.scoring.failure_modes import detect_failure_mode
from adaptive_synth_eval.scoring.response_quality import score_response

logger = setup_logger(__name__)

UNAVAILABLE_ERROR_MARKERS = (
    "chatbot endpoint is not configured",
    "connection refused",
    "failed to establish a new connection",
    "name or service not known",
    "timed out",
    "timeout",
    "unavailable",
    "not reachable",
    "browser has been closed",
    "page has been closed",
)

# Patterns matched against the response *body* when HTTP status appears successful
# but the chatbot is reporting a backend failure (e.g. HTTP 200 with error payload).
UNAVAILABLE_BODY_MARKERS = (
    "error processing request",
    "access to your account is currently revoked",
    "key is either disabled or expired",
    "cosmos db",
    "service unavailable",
    "internal server error",
)


def _validate_profiled_resume_fingerprints(
    state: dict[str, Any], *, contract_fingerprint: str, plan_fingerprint: str
) -> None:
    version = int(state.get("version", 1) or 1)
    if version != 2:
        raise ContractError(
            "Cannot resume a profiled synth run without a v2 fingerprint checkpoint. "
            "Restart the run."
        )
    if state.get("contract_fingerprint") != contract_fingerprint:
        raise ContractError(
            "Cannot resume: the effective contract differs from the profiled "
            "synth run-state checkpoint."
        )
    if state.get("plan_fingerprint") != plan_fingerprint:
        raise ContractError(
            "Cannot resume: the full profiled run plan differs from the run-state "
            "checkpoint."
        )


async def _bounded_results(
    items: list[Any],
    *,
    worker: Callable[[Any], Awaitable[Any]],
    max_concurrency: int,
    can_admit: Callable[[], bool],
) -> AsyncIterator[Any]:
    """Yield completed work while bounding admission and draining on close."""
    iterator = iter(items)
    pending: set[asyncio.Task[Any]] = set()
    unconsumed: set[asyncio.Task[Any]] = set()
    exhausted = False
    limit = max(1, int(max_concurrency))
    try:
        while pending or not exhausted:
            while len(pending) < limit and not exhausted and can_admit():
                try:
                    item = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                pending.add(asyncio.create_task(worker(item)))

            if not pending:
                break

            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            unconsumed = set(done)
            while unconsumed:
                task = unconsumed.pop()
                yield await task
    finally:
        # Closing this generator after result persistence fails must not abandon
        # already-admitted work, including non-cancellable to_thread calls.
        await asyncio.gather(*(pending | unconsumed), return_exceptions=True)


async def _profiled_bounded_results(
    items: list[Any],
    *,
    worker: Callable[[Any], Awaitable[Any]],
    max_concurrency: int,
    can_admit: Callable[[], bool],
) -> AsyncIterator[Any]:
    """Run one profile period at a time and emit each period in planned order."""

    index = 0
    while index < len(items):
        instance_id = items[index].profile_period_instance_id
        end = index + 1
        while (
            end < len(items)
            and items[end].profile_period_instance_id == instance_id
        ):
            end += 1
        group = items[index:end]

        async def indexed(item):
            return item.sequence, await worker(item)

        completed: dict[int, Any] = {}
        expected_sequences = [item.sequence for item in group]
        expected_index = 0
        completed_count = 0
        results = _bounded_results(
            group,
            worker=indexed,
            max_concurrency=max_concurrency,
            can_admit=can_admit,
        )
        try:
            async for sequence, result in results:
                completed_count += 1
                completed[sequence] = result
                while (
                    expected_index < len(expected_sequences)
                    and expected_sequences[expected_index] in completed
                ):
                    next_sequence = expected_sequences[expected_index]
                    expected_index += 1
                    yield completed.pop(next_sequence)
        finally:
            await results.aclose()
        if completed_count < len(group):
            return
        index = end


def run_simulation(
    contract: SimulationContract,
    *,
    dry_run: bool = False,
    output_conversations: bool = False,
    realtime_chat: bool = False,
    interactive_realtime_controls: bool = False,
    persona_filter: str | None = None,
    resume_incomplete: bool = False,
    progress_sink: Callable[[dict[str, Any]], None] | None = None,
    realtime_status_provider: Any | None = None,
) -> dict:
    """Synchronously run the async simulation pipeline for CLI/backwards compatibility."""
    return asyncio.run(
        run_simulation_async(
            contract,
            dry_run=dry_run,
            output_conversations=output_conversations,
            realtime_chat=realtime_chat,
            interactive_realtime_controls=interactive_realtime_controls,
            persona_filter=persona_filter,
            resume_incomplete=resume_incomplete,
            progress_sink=progress_sink,
            realtime_status_provider=realtime_status_provider,
        )
    )


async def run_simulation_async(
    contract: SimulationContract,
    *,
    dry_run: bool = False,
    output_conversations: bool = False,
    realtime_chat: bool = False,
    interactive_realtime_controls: bool = False,
    persona_filter: str | None = None,
    resume_incomplete: bool = False,
    progress_sink: Callable[[dict[str, Any]], None] | None = None,
    realtime_status_provider: Any | None = None,
) -> dict:
    run_start = time.perf_counter()
    run_id = contract.output.run_id or f"run_{int(time.time())}"
    run_dir = Path(contract.output.base_dir) / "runs" / run_id
    personas = contract.persona_by_id()
    scenarios = contract.scenario_by_id()
    matched_persona_id: str | None = None
    if persona_filter:
        for pid in personas:
            if pid.lower() == persona_filter.lower():
                matched_persona_id = pid
                break
        if not matched_persona_id:
            raise ContractError(
                f"Specified persona '{persona_filter}' not found in contract's persona pool: {list(personas.keys())}"
            )
    try:
        full_plan = (
            build_profiled_run_plan(contract, persona_id=matched_persona_id)
            if contract.time_profile is not None
            else build_run_plan(contract.traffic, contract.time_window)
        )
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    plan = list(full_plan)
    resumed_state = load_run_state(run_dir) if resume_incomplete else None
    started_at = (resumed_state or {}).get("started_at") or now_iso()
    completed_conversation_ids = set()
    if resumed_state:
        completed_conversation_ids = {
            str(cid)
            for cid in (resumed_state.get("completed_conversation_ids") or [])
            if cid
        }

    if persona_filter:
        if contract.time_profile is None:
            full_plan = [
                planned
                for planned in full_plan
                if planned.persona_id == matched_persona_id
            ]
            plan = [
                planned for planned in plan if planned.persona_id == matched_persona_id
            ]
        if not plan:
            logger.warning(
                "No conversations planned for persona '%s' in this run.",
                matched_persona_id,
            )

    normalized_contract = contract_to_dict(contract)
    serialized_full_plan = _serialize_synth_plan(full_plan)
    run_state_version = 1
    fingerprint_state: dict[str, Any] = {}
    if contract.time_profile is not None:
        run_state_version = 2
        contract_fingerprint = fingerprint_payload(normalized_contract)
        plan_fingerprint = fingerprint_payload(serialized_full_plan)
        fingerprint_state = {
            "contract_fingerprint": contract_fingerprint,
            "plan_fingerprint": plan_fingerprint,
        }
        if resume_incomplete:
            if resumed_state is None:
                raise ContractError(
                    "Cannot resume a profiled synth run without a run-state "
                    "checkpoint. Restart the run."
                )
            _validate_profiled_resume_fingerprints(
                resumed_state,
                contract_fingerprint=contract_fingerprint,
                plan_fingerprint=plan_fingerprint,
            )

    capture_coordinator = capture_coordinator_from_env(run_dir)
    writer = ArtifactWriter(
        contract.output.base_dir,
        run_id=run_id,
        profile_enabled=contract.time_profile is not None,
        capture_adapter=(
            ChatHistoryProducerAdapter(capture_coordinator)
            if capture_coordinator is not None
            else None
        ),
    )

    if completed_conversation_ids:
        plan = [
            planned
            for planned in plan
            if planned.conversation_id not in completed_conversation_ids
        ]

    planned_conversations_total = len(full_plan)

    client = create_chatbot_client(contract.target, dry_run=dry_run)
    prepare_async = getattr(client, "prepare_async", None)
    prepare = getattr(client, "prepare", None)
    if callable(prepare_async):
        await prepare_async()
    elif callable(prepare):
        await asyncio.to_thread(prepare)

    resume_metrics = (resumed_state or {}).get("metrics") if resumed_state else {}
    errors = int((resume_metrics or {}).get("errors") or 0)
    total_turns = int((resume_metrics or {}).get("total_turns") or 0)
    simulator_prompt_tokens = int(
        (resume_metrics or {}).get("simulator_prompt_tokens") or 0
    )
    simulator_completion_tokens = int(
        (resume_metrics or {}).get("simulator_completion_tokens") or 0
    )
    chatbot_prompt_tokens = int(
        (resume_metrics or {}).get("chatbot_prompt_tokens") or 0
    )
    chatbot_completion_tokens = int(
        (resume_metrics or {}).get("chatbot_completion_tokens") or 0
    )
    wrote_chat_history = (
        resume_incomplete and (writer.run_dir / "chat_history.jsonl").exists()
    )
    wrote_conversations = (
        resume_incomplete and (writer.run_dir / "conversations.jsonl").exists()
    )
    wrote_turns = resume_incomplete and (writer.run_dir / "turns.jsonl").exists()
    wrote_scores = resume_incomplete and (writer.run_dir / "scores.jsonl").exists()
    wrote_conversations_txt = (
        resume_incomplete and (writer.run_dir / "conversations.txt").exists()
    )
    realtime_chat_enabled = realtime_chat
    stopped_early = False
    realtime_controller: RealtimeChatController | None = None
    stop_all_requested = asyncio.Event()
    persona_locks = {
        persona.persona_id: asyncio.Lock() for persona in contract.persona_pool
    }
    persona_total_convos: dict[str, int] = {}
    for planned in plan:
        persona_total_convos[planned.persona_id] = (
            persona_total_convos.get(planned.persona_id, 0) + 1
        )

    if not resume_incomplete:
        write_run_state(
            writer.run_dir,
            {
                "version": run_state_version,
                "mode": "synth",
                "status": "in_progress",
                "run_id": run_id,
                "started_at": started_at,
                "updated_at": now_iso(),
                "total_planned_conversations": planned_conversations_total,
                "completed_conversations": 0,
                "completed_conversation_ids": [],
                "metrics": {
                    "errors": 0,
                    "total_turns": 0,
                    "simulator_prompt_tokens": 0,
                    "simulator_completion_tokens": 0,
                    "chatbot_prompt_tokens": 0,
                    "chatbot_completion_tokens": 0,
                },
                **fingerprint_state,
            },
        )
    processed_conversation_ids = set(completed_conversation_ids)

    if progress_sink is not None:
        progress_sink(
            {
                "phase": "running",
                "completed": len(processed_conversation_ids),
                "total": planned_conversations_total,
                "last_item": None,
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "details": {"remaining": len(plan)},
            }
        )

    if interactive_realtime_controls and not realtime_chat:
        logger.warning(
            "Interactive realtime controls require --realtime-chat; skipping controls."
        )

    if realtime_chat_enabled and interactive_realtime_controls:
        single_persona_mode = (len(personas) <= 1) or (persona_filter is not None)
        realtime_controller = RealtimeChatController(
            personas=personas,
            single_persona_mode=single_persona_mode,
            persona_total_convos=persona_total_convos,
            status_provider=realtime_status_provider,
        )
        if matched_persona_id:
            realtime_controller.set_active_persona(matched_persona_id)
        elif contract.persona_pool:
            realtime_controller.set_active_persona(contract.persona_pool[0].persona_id)
        start_async = getattr(realtime_controller, "start_async", None)
        if callable(start_async):
            await start_async()
        else:
            realtime_controller.start()

    def _request_stop_all() -> None:
        if not stop_all_requested.is_set():
            stop_all_requested.set()
        if realtime_controller:
            realtime_controller.stop()

    def _is_target_chatbot_unavailable(response) -> bool:
        if response.error:
            error_text = response.error.lower()
            if response.status_code == 0:
                return True
            if response.status_code >= 500:
                return True
            if any(marker in error_text for marker in UNAVAILABLE_ERROR_MARKERS):
                return True
        # Also catch cases where HTTP 200 is returned but the body signals an error
        if response.bot_response:
            body_text = response.bot_response.lower()
            if any(marker in body_text for marker in UNAVAILABLE_BODY_MARKERS):
                return True
        return False

    def _unavailability_detail(response) -> str:
        """Return a short human-readable detail string for the stop log."""
        if response.error:
            return f"error={response.error!r}, status={response.status_code}"
        if response.bot_response:
            first_line = response.bot_response.splitlines()[0][:200]
            return f"status={response.status_code}, body={first_line!r}"
        return f"status={response.status_code}"

    async def process_conversation(planned):
        if stop_all_requested.is_set():
            row = {
                "conversation_id": planned.conversation_id,
                "session_id": planned.session_id,
                "persona_id": planned.persona_id,
                "scenario_id": planned.scenario_id,
                "synthetic_day": planned.synthetic_day.isoformat(),
                "turn_count": 0,
            }
            if contract.time_profile is not None:
                row.update(
                    timestamp=planned.synthetic_timestamp.isoformat(),
                    **profile_provenance(planned),
                )
            return (
                row,
                [],
                [],
                [],
                0,
            )
        async with persona_locks[planned.persona_id]:
            return await _process_conversation_locked(planned)

    async def _process_conversation_locked(planned):
        if stop_all_requested.is_set():
            row = {
                "conversation_id": planned.conversation_id,
                "session_id": planned.session_id,
                "persona_id": planned.persona_id,
                "scenario_id": planned.scenario_id,
                "synthetic_day": planned.synthetic_day.isoformat(),
                "turn_count": 0,
            }
            if contract.time_profile is not None:
                row.update(
                    timestamp=planned.synthetic_timestamp.isoformat(),
                    **profile_provenance(planned),
                )
            return (
                row,
                [],
                [],
                [],
                0,
            )

        local_records = []
        local_turn_rows = []
        local_score_rows = []
        local_errors = 0

        persona = personas[planned.persona_id]
        scenario = scenarios[planned.scenario_id]

        memory_file = writer.run_dir / "personas" / f"{planned.persona_id}_memory.md"
        simulator = UserSimulator(
            persona,
            scenario,
            turn_count=planned.turn_count,
            seed=hash(planned.conversation_id) % 10_000,
            memory_file=memory_file,
            llm_config=asdict(contract.llm),
        )

        local_conversation_row = {
            "conversation_id": planned.conversation_id,
            "session_id": planned.session_id,
            "persona_id": planned.persona_id,
            "scenario_id": planned.scenario_id,
            "synthetic_day": planned.synthetic_day.isoformat(),
            "turn_count": 0,
        }
        if contract.time_profile is not None:
            local_conversation_row.update(
                timestamp=planned.synthetic_timestamp.isoformat(),
                **profile_provenance(planned),
            )

        previous_bot_response = None
        chatbot_history_tokens = 0
        for turn_id in range(1, planned.turn_count + 1):
            if stop_all_requested.is_set():
                break
            if realtime_controller and realtime_controller.stop_requested:
                break
            if realtime_controller:
                wait_async = getattr(realtime_controller, "wait_if_paused_async", None)
                can_continue = (
                    await wait_async()
                    if callable(wait_async)
                    else await asyncio.to_thread(realtime_controller.wait_if_paused)
                )
                if not can_continue:
                    break

            # Get behavior mode for the current persona (persona-specific or global fallback)
            behavior_override = resolve_behavior_override(
                (
                    planned.behavior_mode
                    if contract.time_profile is not None
                    else None
                ),
                realtime_controller,
                simulator.persona.persona_id,
            )
            turn_profile = (
                profile_turn_provenance(
                    planned, turn_id=turn_id, turn_count=planned.turn_count
                )
                if contract.time_profile is not None
                else {}
            )
            logger.info(
                "[%s|turn=%s] Persona thinking started (provider=%s, behavior=%s)...",
                planned.conversation_id,
                turn_id,
                "llm" if simulator.llm_client.enabled else "fallback",
                behavior_override or "default",
            )
            human_start = time.perf_counter()
            turn = await simulator.generate_turn_async(
                turn_id,
                previous_bot_response,
                behavior_override=behavior_override,
            )
            human_elapsed_ms = (time.perf_counter() - human_start) * 1000
            logger.info(
                "[%s|turn=%s] Persona thinking completed in %.2f ms; message_length=%s",
                planned.conversation_id,
                turn_id,
                human_elapsed_ms,
                len(turn.user_message),
            )

            should_render = True
            if realtime_controller and realtime_controller.active_persona_id:
                should_render = (
                    simulator.persona.persona_id
                    == realtime_controller.active_persona_id
                )

            if realtime_chat_enabled:
                if should_render:
                    await asyncio.to_thread(
                        display_persona_message,
                        conversation_id=planned.conversation_id,
                        persona_id=simulator.persona.persona_id,
                        scenario_id=planned.scenario_id,
                        turn_id=turn.turn_id,
                        human_message=turn.user_message,
                    )

            logger.info(
                "[%s|turn=%s] Sending request to chatbot and waiting for response...",
                planned.conversation_id,
                turn.turn_id,
            )
            chatbot_wait_start = time.perf_counter()
            chatbot_prompt_tokens = chatbot_history_tokens + count_tokens(
                turn.user_message
            )
            response = await client.send_async(
                conversation_id=planned.conversation_id,
                session_id=planned.session_id,
                turn_id=turn.turn_id,
                user_message=turn.user_message,
                metadata={
                    "persona_id": simulator.persona.persona_id,
                    "scenario_id": planned.scenario_id,
                    "synthetic": True,
                    **turn_profile,
                },
            )
            chatbot_wait_ms = (time.perf_counter() - chatbot_wait_start) * 1000
            logger.info(
                "[%s|turn=%s] Chatbot response received in %.2f ms (http_latency_ms=%s, status=%s, error=%s)",
                planned.conversation_id,
                turn.turn_id,
                chatbot_wait_ms,
                response.latency_ms,
                response.status_code,
                response.error or "none",
            )
            chatbot_completion_tokens = count_tokens(response.bot_response)
            chatbot_history_tokens += (
                count_tokens(turn.user_message) + chatbot_completion_tokens
            )
            if response.error or _is_target_chatbot_unavailable(response):
                local_errors += 1
                if _is_target_chatbot_unavailable(response):
                    logger.error(
                        "[%s|turn=%s] Target chatbot is unavailable; stopping all simulation processes. Detail: %s",
                        planned.conversation_id,
                        turn.turn_id,
                        _unavailability_detail(response),
                    )
                    _request_stop_all()
                    break
            previous_bot_response = response.bot_response

            if realtime_chat_enabled:
                if should_render:
                    await asyncio.to_thread(
                        display_bot_message,
                        bot_message=response.bot_response,
                    )

            score = score_response(
                user_message=turn.user_message,
                bot_response=response.bot_response,
                expected_context=scenario.context,
                missing_context_expected="missing_information"
                in turn.applied_failure_modes,
            )
            failure_mode = detect_failure_mode(
                response.bot_response, response.error, score.safety_score
            )
            gen_meta = (
                dict(turn.generation_metadata) if turn.generation_metadata else {}
            )
            gen_meta["chatbot_prompt_tokens"] = chatbot_prompt_tokens
            gen_meta["chatbot_completion_tokens"] = chatbot_completion_tokens

            record = ChatHistoryRecord(
                conversation_id=planned.conversation_id,
                session_id=planned.session_id,
                synthetic_day=planned.synthetic_day,
                persona_id=simulator.persona.persona_id,
                scenario_id=planned.scenario_id,
                turn_id=turn.turn_id,
                user_message=turn.user_message,
                bot_response=response.bot_response,
                expected_retrieval_topics=scenario.expected_retrieval_topics,
                planned_failure_modes=turn.planned_failure_modes,
                applied_failure_modes=turn.applied_failure_modes,
                reference_context=scenario.context,
                reference_answer=scenario.reference_answer,
                groundedness_score=score.groundedness_score,
                relevance_score=score.relevance_score,
                safety_score=score.safety_score,
                clarification_score=score.clarification_score,
                failure_mode=failure_mode,
                latency_ms=response.latency_ms,
                status_code=response.status_code,
                error=response.error,
                synthetic_flag=contract.synthetic_flag,
                retrieved_policy_ids=response.retrieved_policy_ids,
                response_raw=response.raw,
                generation_metadata=gen_meta,
                **turn_profile,
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
                    **turn_profile,
                }
            )

            if realtime_controller:
                wait_async = getattr(
                    realtime_controller, "wait_for_turn_delay_async", None
                )
                can_continue = (
                    await wait_async()
                    if callable(wait_async)
                    else await asyncio.to_thread(
                        realtime_controller.wait_for_turn_delay
                    )
                )
                if not can_continue:
                    break

        # Summarize conversation and update long-term recall
        await asyncio.to_thread(simulator.save_conversation_summary_to_long_term_recall)

        if realtime_controller:
            realtime_controller.notify_conversation_complete(planned.persona_id)

        return (
            local_conversation_row,
            local_records,
            local_turn_rows,
            local_score_rows,
            local_errors,
        )

    try:
        max_concurrency = _effective_max_concurrency(contract)
        results_factory = (
            _profiled_bounded_results
            if contract.time_profile is not None
            else _bounded_results
        )
        completed_results = results_factory(
            plan,
            worker=process_conversation,
            max_concurrency=max_concurrency,
            can_admit=lambda: not stop_all_requested.is_set(),
        )
        try:
            async for completed in completed_results:
                conv_row, loc_recs, loc_turn_rows, loc_score_rows, loc_errs = completed
                conversation_id = str(conv_row.get("conversation_id") or "")
                if conversation_id:
                    processed_conversation_ids.add(conversation_id)
                errors += loc_errs
                total_turns += conv_row.get("turn_count", 0)

                if loc_recs:
                    chat_rows = [rec.to_dict() for rec in loc_recs]
                    writer.append_chat_history_rows(
                        chat_rows, overwrite=not wrote_chat_history
                    )
                    wrote_chat_history = True

                    simulator_prompt_tokens += sum(
                        (rec.generation_metadata or {}).get(
                            "simulator_prompt_tokens", 0
                        )
                        for rec in loc_recs
                    )
                    simulator_completion_tokens += sum(
                        (rec.generation_metadata or {}).get(
                            "simulator_completion_tokens", 0
                        )
                        for rec in loc_recs
                    )
                    chatbot_prompt_tokens += sum(
                        (rec.generation_metadata or {}).get("chatbot_prompt_tokens", 0)
                        for rec in loc_recs
                    )
                    chatbot_completion_tokens += sum(
                        (rec.generation_metadata or {}).get(
                            "chatbot_completion_tokens", 0
                        )
                        for rec in loc_recs
                    )

                    if output_conversations:
                        writer.append_conversation_txt(
                            loc_recs, overwrite=not wrote_conversations_txt
                        )
                        wrote_conversations_txt = True

                writer.append_jsonl(
                    "conversations.jsonl", [conv_row], overwrite=not wrote_conversations
                )
                wrote_conversations = True

                if progress_sink is not None:
                    completed = len(processed_conversation_ids)
                    elapsed_seconds = max(0.0, time.perf_counter() - run_start)
                    progress_sink(
                        {
                            "phase": "running",
                            "completed": completed,
                            "total": planned_conversations_total,
                            "last_item": conversation_id,
                            "elapsed_seconds": elapsed_seconds,
                            "eta_seconds": None,
                            "details": {
                                "remaining": max(
                                    planned_conversations_total - completed, 0
                                )
                            },
                        }
                    )

                if loc_turn_rows:
                    writer.append_jsonl(
                        "turns.jsonl", loc_turn_rows, overwrite=not wrote_turns
                    )
                    wrote_turns = True

                if loc_score_rows:
                    writer.append_jsonl(
                        "scores.jsonl", loc_score_rows, overwrite=not wrote_scores
                    )
                    wrote_scores = True

                write_run_state(
                    writer.run_dir,
                    {
                        "version": run_state_version,
                        "mode": "synth",
                        "status": "in_progress",
                        "run_id": run_id,
                        "started_at": started_at,
                        "updated_at": now_iso(),
                        "total_planned_conversations": planned_conversations_total,
                        "completed_conversations": len(processed_conversation_ids),
                        "completed_conversation_ids": sorted(
                            processed_conversation_ids
                        ),
                        "metrics": {
                            "errors": errors,
                            "total_turns": total_turns,
                            "simulator_prompt_tokens": simulator_prompt_tokens,
                            "simulator_completion_tokens": simulator_completion_tokens,
                            "chatbot_prompt_tokens": chatbot_prompt_tokens,
                            "chatbot_completion_tokens": chatbot_completion_tokens,
                        },
                        **fingerprint_state,
                    },
                )
        except BaseException:
            stop_all_requested.set()
            raise
        finally:
            await completed_results.aclose()

        if realtime_controller and realtime_controller.stop_requested:
            stopped_early = True
        if stop_all_requested.is_set():
            stopped_early = True
    finally:
        close_client_async = getattr(client, "close_async", None)
        close_client = getattr(client, "close", None)
        if close_client_async:
            await close_client_async()
        elif callable(close_client):
            await asyncio.to_thread(close_client)
        if realtime_controller:
            stop_async = getattr(realtime_controller, "stop_async", None)
            if callable(stop_async):
                await stop_async()
            else:
                realtime_controller.stop()

    elapsed_seconds = round(time.perf_counter() - run_start, 2)

    # Simulator LLM Token Statistics
    simulator_total_tokens = simulator_prompt_tokens + simulator_completion_tokens

    completed_conversations = len(processed_conversation_ids)
    avg_prompt_tokens_convo = (
        round(simulator_prompt_tokens / completed_conversations, 2)
        if completed_conversations
        else 0.0
    )
    avg_completion_tokens_convo = (
        round(simulator_completion_tokens / completed_conversations, 2)
        if completed_conversations
        else 0.0
    )
    avg_total_tokens_convo = (
        round(simulator_total_tokens / completed_conversations, 2)
        if completed_conversations
        else 0.0
    )

    # Chatbot LLM Token Statistics
    chatbot_total_tokens = chatbot_prompt_tokens + chatbot_completion_tokens

    avg_chatbot_prompt_tokens_convo = (
        round(chatbot_prompt_tokens / completed_conversations, 2)
        if completed_conversations
        else 0.0
    )
    avg_chatbot_completion_tokens_convo = (
        round(chatbot_completion_tokens / completed_conversations, 2)
        if completed_conversations
        else 0.0
    )
    avg_chatbot_total_tokens_convo = (
        round(chatbot_total_tokens / completed_conversations, 2)
        if completed_conversations
        else 0.0
    )

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

    # Scale Projections
    convo_count = completed_conversations
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

    # Production Realism
    # 1. Mix Distribution Realism
    total_mix_weight = (
        sum(item.weight for item in contract.traffic.mix)
        if contract.traffic.mix
        else 1.0
    )
    mix_targets = {}
    for item in contract.traffic.mix:
        key = f"{item.persona_id} + {item.scenario_id}"
        mix_targets[key] = item.weight / total_mix_weight

    actual_mix_counts = {}
    for planned in full_plan:
        key = f"{planned.persona_id} + {planned.scenario_id}"
        actual_mix_counts[key] = actual_mix_counts.get(key, 0) + 1

    mix_realism = []
    for key, target_pct in mix_targets.items():
        actual_count = actual_mix_counts.get(key, 0)
        actual_pct = actual_count / len(full_plan) if full_plan else 0.0
        mix_realism.append(
            {
                "mix": key,
                "target_pct": round(target_pct * 100, 2),
                "actual_pct": round(actual_pct * 100, 2),
                "actual_count": actual_count,
            }
        )

    # 2. Persona Distribution Realism
    persona_weights = {}
    for item in contract.traffic.mix:
        persona_weights[item.persona_id] = (
            persona_weights.get(item.persona_id, 0.0) + item.weight
        )
    total_persona_weight = sum(persona_weights.values()) or 1.0
    persona_targets = {
        pid: w / total_persona_weight for pid, w in persona_weights.items()
    }

    actual_persona_counts = {}
    for planned in full_plan:
        actual_persona_counts[planned.persona_id] = (
            actual_persona_counts.get(planned.persona_id, 0) + 1
        )

    persona_realism = []
    for pid, target_pct in persona_targets.items():
        actual_count = actual_persona_counts.get(pid, 0)
        actual_pct = actual_count / len(full_plan) if full_plan else 0.0
        persona_realism.append(
            {
                "persona_id": pid,
                "target_pct": round(target_pct * 100, 2),
                "actual_pct": round(actual_pct * 100, 2),
                "actual_count": actual_count,
            }
        )

    # 3. Scenario Distribution Realism
    scenario_weights = {}
    for item in contract.traffic.mix:
        scenario_weights[item.scenario_id] = (
            scenario_weights.get(item.scenario_id, 0.0) + item.weight
        )
    total_scenario_weight = sum(scenario_weights.values()) or 1.0
    scenario_targets = {
        sid: w / total_scenario_weight for sid, w in scenario_weights.items()
    }

    actual_scenario_counts = {}
    for planned in full_plan:
        actual_scenario_counts[planned.scenario_id] = (
            actual_scenario_counts.get(planned.scenario_id, 0) + 1
        )

    scenario_realism = []
    for sid, target_pct in scenario_targets.items():
        actual_count = actual_scenario_counts.get(sid, 0)
        actual_pct = actual_count / len(full_plan) if full_plan else 0.0
        scenario_realism.append(
            {
                "scenario_id": sid,
                "target_pct": round(target_pct * 100, 2),
                "actual_pct": round(actual_pct * 100, 2),
                "actual_count": actual_count,
            }
        )

    # 4. Temporal Distribution Realism
    from adaptive_synth_eval.generation.traffic import _day_weights

    day_weights = _day_weights(contract.traffic, contract.time_window)
    total_day_weight = sum(day_weights) or 1.0
    day_targets = [w / total_day_weight for w in day_weights]

    actual_day_counts = [0] * contract.time_window.num_synthetic_days
    for planned in full_plan:
        day_offset = (planned.synthetic_day - contract.time_window.start_day).days
        if 0 <= day_offset < len(actual_day_counts):
            actual_day_counts[day_offset] += 1

    temporal_realism = []
    for idx, target_pct in enumerate(day_targets):
        actual_count = actual_day_counts[idx]
        actual_pct = actual_count / len(full_plan) if full_plan else 0.0
        temporal_realism.append(
            {
                "day": idx + 1,
                "target_pct": round(target_pct * 100, 2),
                "actual_pct": round(actual_pct * 100, 2),
                "actual_count": actual_count,
            }
        )

    production_realism = {
        "mix_realism": mix_realism,
        "persona_realism": persona_realism,
        "scenario_realism": scenario_realism,
        "temporal_realism": temporal_realism,
    }

    configured_max_concurrency = int(
        getattr(contract.traffic, "max_concurrency", 5) or 5
    )
    effective_max_concurrency = _effective_max_concurrency(contract)

    summary = {
        "run_id": run_id,
        "total_conversations": completed_conversations,
        "total_turns": total_turns,
        "errors": errors,
        "dry_run": dry_run,
        "stopped_early": stopped_early,
        "elapsed_seconds": elapsed_seconds,
        "output_dir": str(writer.run_dir),
        "configured_max_concurrency": configured_max_concurrency,
        "effective_max_concurrency": effective_max_concurrency,
        "tokens": tokens_stats,
        "scale_projections": scale_projections,
        "production_realism": production_realism,
    }
    if contract.time_profile is not None:
        summary["profile_counts"] = summarize_profile_plan(full_plan)
    writer.write_json("contract.normalized.json", normalized_contract)
    writer.write_json("run_plan.json", serialized_full_plan)

    if not wrote_chat_history:
        writer.append_chat_history_rows([], overwrite=True)
    if not wrote_conversations:
        writer.write_jsonl("conversations.jsonl", [])
    if not wrote_turns:
        writer.write_jsonl("turns.jsonl", [])
    if not wrote_scores:
        writer.write_jsonl("scores.jsonl", [])
    if output_conversations and not wrote_conversations_txt:
        writer.append_conversation_txt([], overwrite=True)

    writer.write_json("run_summary.json", summary)
    writer.write_generation_report(summary)

    write_run_state(
        writer.run_dir,
        {
            "version": run_state_version,
            "mode": "synth",
            "status": "completed",
            "run_id": run_id,
            "started_at": started_at,
            "updated_at": now_iso(),
            "completed_at": now_iso(),
            "total_planned_conversations": planned_conversations_total,
            "completed_conversations": completed_conversations,
            "completed_conversation_ids": sorted(processed_conversation_ids),
            "metrics": {
                "errors": errors,
                "total_turns": total_turns,
                "simulator_prompt_tokens": simulator_prompt_tokens,
                "simulator_completion_tokens": simulator_completion_tokens,
                "chatbot_prompt_tokens": chatbot_prompt_tokens,
                "chatbot_completion_tokens": chatbot_completion_tokens,
            },
            "summary": summary,
            **fingerprint_state,
        },
    )

    return summary


def _effective_max_concurrency(contract: SimulationContract) -> int:
    if contract.target.mode == "browser":
        return 1
    return max(1, int(getattr(contract.traffic, "max_concurrency", 5) or 5))


def _serialize_synth_plan(plan: list[Any]) -> list[dict[str, Any]]:
    if not plan or not hasattr(plan[0], "profile_period_id"):
        return [item.__dict__ for item in plan]
    rows = []
    for item in plan:
        rows.append(
            {
                "conversation_id": item.conversation_id,
                "session_id": item.session_id,
                "persona_id": item.persona_id,
                "scenario_id": item.scenario_id,
                "synthetic_day": item.synthetic_day.isoformat(),
                "turn_count": item.turn_count,
                "sequence": item.sequence,
                **profile_provenance(item),
            }
        )
    return rows
