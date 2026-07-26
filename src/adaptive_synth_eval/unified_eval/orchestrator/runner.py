"""Top-level fan-out: plans conversations from a UnifiedContract, runs them concurrently,
writes unified artifacts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import random
import time
from collections import deque
from datetime import datetime, timedelta
from glob import glob
from pathlib import Path
from typing import Any, Callable

from adaptive_synth_eval.adversarial_response_engine.core.models import AttackMemory
from adaptive_synth_eval.adversarial_response_engine.core.token_budget import (
    TokenBudgetManager,
)
from adaptive_synth_eval.artifacts.run_state import (
    load_run_state,
    now_iso,
    write_run_state,
)
from adaptive_synth_eval.clients.chatbot_factory import create_chatbot_client
from adaptive_synth_eval.clients.logger_utils import attach_run_file_log
from adaptive_synth_eval.capture.producers import (
    AttackMemoryProducerAdapter,
    ChatHistoryProducerAdapter,
    PersonaMemoryProducerAdapter,
)
from adaptive_synth_eval.capture.runtime import capture_coordinator_from_env
from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController
from adaptive_synth_eval.unified_eval.config.contract import contract_to_dict
from adaptive_synth_eval.unified_eval.config.schemas import UnifiedContract
from adaptive_synth_eval.unified_eval.orchestrator.artifact_actor import ArtifactActor
from adaptive_synth_eval.unified_eval.orchestrator.coin_flip import (
    make_conversation_rng,
)
from adaptive_synth_eval.unified_eval.orchestrator.conversation import (
    ConversationResult,
    run_conversation,
)
from adaptive_synth_eval.unified_eval.orchestrator.memory_registry import (
    AttackMemoryRegistry,
)
from adaptive_synth_eval.unified_eval.orchestrator.persona_memory_actor import (
    PersonaMemoryActor,
)
from adaptive_synth_eval.unified_eval.output.writer import UnifiedArtifactWriter
from adaptive_synth_eval.unified_eval.providers.budget_meter import BudgetMeter
from adaptive_synth_eval.unified_eval.providers.llm_factory import build_component_llms
from adaptive_synth_eval.unified_eval.providers.llm_target_client import LLMTargetClient

logger = logging.getLogger(__name__)


def _secret_safe_payload(value: Any, *, redact: bool = False) -> Any:
    if redact:
        if isinstance(value, dict):
            return {str(key): "<redacted>" for key in value}
        return "<redacted>"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lowered = str(key).lower()
            sensitive = (
                lowered == "auth"
                or "password" in lowered
                or "secret" in lowered
                or ("token" in lowered and lowered != "max_tokens")
                or ("api_key" in lowered and lowered != "api_key_env")
            )
            out[str(key)] = _secret_safe_payload(item, redact=sensitive)
        return out
    if isinstance(value, (list, tuple)):
        return [_secret_safe_payload(item) for item in value]
    return value


def _fingerprint_payload(payload: Any) -> str:
    canonical = json.dumps(
        _secret_safe_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_resume_fingerprints(
    state: dict[str, Any], *, contract_fingerprint: str, plan_fingerprint: str
) -> None:
    version = int(state.get("version", 1) or 1)
    if version > 2:
        raise ContractError(
            f"Unsupported unified run-state version {version}; supported versions are 1 and 2."
        )
    if version == 1:
        logger.warning(
            "Resuming legacy run-state v1 without contract/plan fingerprints; "
            "using best-effort compatibility behavior."
        )
        return
    if state.get("contract_fingerprint") != contract_fingerprint:
        raise ContractError(
            "Cannot resume: the effective contract differs from the run-state checkpoint."
        )
    if state.get("plan_fingerprint") != plan_fingerprint:
        raise ContractError(
            "Cannot resume: the filtered run plan differs from the run-state checkpoint."
        )


async def _run_sliding_window(
    items: list[Any],
    *,
    worker,
    max_concurrency: int,
    can_admit,
) -> None:
    """Run a bounded task window, rechecking admission after every completion."""
    iterator = iter(items)
    pending: set[asyncio.Task] = set()
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
            failure: BaseException | None = None
            for task in done:
                try:
                    await task
                except BaseException as exc:
                    if failure is None:
                        failure = exc

            if failure is not None:
                raise failure
    finally:
        # Work already admitted may be executing in asyncio.to_thread(), which
        # cancellation cannot stop. Drain it on worker failure, supervisor
        # cancellation, or any other exceptional exit before resources close.
        await asyncio.gather(*pending, return_exceptions=True)


async def _prepare_client(client: Any) -> None:
    """Finish lazy shared-client construction before concurrent workers start."""
    prepare_async = getattr(client, "prepare_async", None)
    if callable(prepare_async):
        await prepare_async()
        return
    prepare = getattr(client, "prepare", None)
    if callable(prepare):
        await asyncio.to_thread(prepare)


def _seed_attack_memory(spec: str | list[str], max_entries: int) -> AttackMemory:
    """Pool prior runs' attack memory into one capped store. Missing/bad files are skipped."""
    specs = [spec] if isinstance(spec, str) else spec
    paths = sorted({p for s in specs for p in glob(str(Path(s).expanduser()))})
    memory = AttackMemory(max_entries=max_entries)
    for path in paths:
        try:
            loaded = AttackMemory.from_dict(
                json.loads(Path(path).read_text()), max_entries
            )
            memory.merge(loaded.snapshot())
        except (OSError, ValueError) as exc:
            logger.warning("Skipping attack-memory seed %s: %s", path, exc)
    logger.info(
        "Seeded attack memory from %d file(s): %d entries",
        len(paths),
        len(memory.snapshot()),
    )
    return memory


class _RunProgressTracker:
    """Emit periodic run progress as conversations complete."""

    def __init__(
        self,
        *,
        total: int | None,
        enabled: bool = True,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.total = total
        self.enabled = enabled
        self.completed = 0
        self.started_monotonic = time.perf_counter()
        self._progress_sink = progress_sink
        self._lock = asyncio.Lock()

    def _emit_progress_snapshot(
        self,
        *,
        conversation_id: str,
        completed: int,
        elapsed_seconds: float,
        remaining: int | None = None,
        eta_seconds: float | None = None,
    ) -> None:
        if self._progress_sink is None:
            return
        try:
            self._progress_sink(
                {
                    "phase": "running",
                    "completed": completed,
                    "total": self.total,
                    "last_item": conversation_id,
                    "elapsed_seconds": elapsed_seconds,
                    "eta_seconds": eta_seconds,
                    "details": {"remaining": remaining},
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Progress sink failed; continuing without live status updates."
            )

    async def mark_completed(self, conversation_id: str) -> None:
        async with self._lock:
            self.completed += 1
            completed = self.completed
            elapsed_seconds = max(0.0, time.perf_counter() - self.started_monotonic)

            if self.total is None:
                if not self.enabled:
                    # Realtime mode may suppress progress logs to reduce noise, but status
                    # consumers still need every completion update.
                    self._emit_progress_snapshot(
                        conversation_id=conversation_id,
                        completed=completed,
                        elapsed_seconds=elapsed_seconds,
                    )
                    return
                # Unknown total (budget-driven runs): emit periodically to avoid noisy logs.
                if completed != 1 and completed % 25 != 0:
                    return
                self._emit_progress_snapshot(
                    conversation_id=conversation_id,
                    completed=completed,
                    elapsed_seconds=elapsed_seconds,
                )
                logger.info(
                    "[PROGRESS] ts=%s done=%d left=unknown elapsed=%s eta=unknown last=%s",
                    _now_iso_timestamp(),
                    completed,
                    _format_duration(elapsed_seconds),
                    conversation_id,
                )
                return

            step = max(1, self.total // 100)
            should_emit = (
                completed == 1 or completed == self.total or completed % step == 0
            )
            if not should_emit:
                return

            remaining = max(self.total - completed, 0)
            eta_seconds = _estimate_remaining_seconds(
                completed=completed,
                total=self.total,
                elapsed_seconds=elapsed_seconds,
            )

            if not self.enabled:
                self._emit_progress_snapshot(
                    conversation_id=conversation_id,
                    completed=completed,
                    elapsed_seconds=elapsed_seconds,
                    remaining=remaining,
                    eta_seconds=eta_seconds,
                )
                return

            eta_str = _format_eta_timestamp(eta_seconds)
            completion_pct = (completed / self.total) * 100 if self.total > 0 else 100.0
            self._emit_progress_snapshot(
                conversation_id=conversation_id,
                completed=completed,
                elapsed_seconds=elapsed_seconds,
                remaining=remaining,
                eta_seconds=eta_seconds,
            )
            logger.info(
                "[PROGRESS] ts=%s done=%d/%d pct=%.1f%% left=%d elapsed=%s eta=%s last=%s",
                _now_iso_timestamp(),
                completed,
                self.total,
                completion_pct,
                remaining,
                _format_duration(elapsed_seconds),
                eta_str,
                conversation_id,
            )


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
    resume_incomplete: bool = False,
    progress_sink: Callable[[dict[str, Any]], None] | None = None,
    realtime_status_provider: Any | None = None,
) -> dict[str, Any]:
    """Synchronous entry — wraps the async runner for the CLI."""
    return asyncio.run(
        run_unified_async(
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
            resume_incomplete=resume_incomplete,
            progress_sink=progress_sink,
            realtime_status_provider=realtime_status_provider,
        )
    )


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
    resume_incomplete: bool = False,
    progress_sink: Callable[[dict[str, Any]], None] | None = None,
    realtime_status_provider: Any | None = None,
) -> dict[str, Any]:
    persona_filter = _resolve_persona_filter(contract, persona_filter)
    if run_id_override:
        # Explicit --run-id is used verbatim so resume/restart can target a known run.
        run_id = run_id_override
    elif contract.output.run_id:
        # Append a runtime timestamp to the contract's run_id so re-running the same
        # YAML writes to a fresh directory instead of overwriting prior artifacts.
        run_id = f"{contract.output.run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        run_id = f"unified_run_{int(time.time())}"
    run_dir = Path(contract.output.base_dir) / "runs" / run_id
    capture_coordinator = capture_coordinator_from_env(run_dir)
    chat_capture_adapter = (
        ChatHistoryProducerAdapter(capture_coordinator)
        if capture_coordinator is not None
        else None
    )
    persona_capture_adapter = (
        PersonaMemoryProducerAdapter(capture_coordinator)
        if capture_coordinator is not None
        else None
    )
    attack_capture_adapter = (
        AttackMemoryProducerAdapter(capture_coordinator)
        if capture_coordinator is not None
        else None
    )
    writer = UnifiedArtifactWriter(
        contract.output.base_dir,
        run_id=run_id,
        capture_adapter=chat_capture_adapter,
    )
    # Persist this run's log lines (including the per-turn trajectory logs) to run.log
    # alongside the other artifacts, in addition to console / optional CloudWatch output.
    attach_run_file_log(writer.run_dir)
    resumed_state = load_run_state(writer.run_dir) if resume_incomplete else None
    started_at = (resumed_state or {}).get("started_at") or now_iso()
    completed_conversation_ids = {
        str(cid)
        for cid in ((resumed_state or {}).get("completed_conversation_ids") or [])
        if cid
    }

    # Initialize / clean slate for progressive artifact writing.
    if not resume_incomplete:
        writer.write_jsonl("conversations.jsonl", [])
        writer.write_jsonl("turns.jsonl", [])
        writer.write_jsonl("scores.jsonl", [])
        writer.write_jsonl("failed_examples.jsonl", [])
        writer.write_jsonl("adversarial_sessions.jsonl", [])
        writer.write_jsonl("chat_history.jsonl", [])
        writer._write_csv("chat_history.csv", [], append=False)
        if output_conversations:
            (writer.run_dir / "conversations.txt").write_text("", encoding="utf-8")
    else:
        _ensure_progressive_artifacts_exist(
            writer=writer, output_conversations=output_conversations
        )

    # Build LLM clients for each component (mock when dry_run regardless of contract.llm.provider).
    if dry_run:
        contract = _force_mock_providers(contract)
    llms = build_component_llms(contract)
    await asyncio.gather(
        *(asyncio.to_thread(provided.prepare) for provided in llms.values())
    )

    # Shared resources (built BEFORE target so the meter can hook into the target client).
    state_version = int((resumed_state or {}).get("version", 1) or 1)
    restored_meter = (resumed_state or {}).get("meter") if state_version == 2 else None
    if isinstance(restored_meter, dict):
        stored_max = int(
            (restored_meter.get("budget") or {}).get(
                "max_total_tokens", contract.run.budget
            )
        )
        if stored_max != contract.run.budget:
            raise ContractError(
                "Cannot resume: run.budget differs from the v2 checkpoint. Restart the run."
            )
        meter = BudgetMeter.from_snapshot(
            restored_meter, max_total_tokens=contract.run.budget
        )
        token_budget = meter.budget
    else:
        token_budget = TokenBudgetManager(max_total_tokens=contract.run.budget)
        meter = BudgetMeter(budget=token_budget)
    # Pre-register every component so the per_component breakdown is present even
    # if no calls were made (e.g. dry-run with zero adversarial turns).
    for component in ("planner", "generator", "judge", "policy", "user_simulator"):
        if component in llms:
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
            max_concurrency=max_concurrency_override
            or _effective_max_concurrency(contract),
        )
    await _prepare_client(target)

    restored_memory = (
        (resumed_state or {}).get("attack_memory") if state_version == 2 else None
    )
    if isinstance(restored_memory, dict):
        if restored_memory.get("mode") != contract.eval_plan.attack_memory:
            raise ContractError(
                "Cannot resume: eval_plan.attack_memory differs from the v2 checkpoint."
            )
        if (
            int(restored_memory.get("max_entries", 50))
            != contract.eval_plan.attack_memory_max_entries
        ):
            raise ContractError(
                "Cannot resume: attack_memory_max_entries differs from the v2 checkpoint."
            )
        memory_registry = AttackMemoryRegistry.from_dict(
            restored_memory,
            capture_adapter=attack_capture_adapter,
        )
        if contract.eval_plan.seed_attack_memory_path:
            logger.warning(
                "Ignoring seed_attack_memory_path because restored v2 memory supersedes seeds."
            )
    else:
        shared_seed = None
        if (
            contract.eval_plan.attack_memory == "shared"
            and contract.eval_plan.seed_attack_memory_path
        ):
            shared_seed = _seed_attack_memory(
                contract.eval_plan.seed_attack_memory_path,
                contract.eval_plan.attack_memory_max_entries,
            )
        memory_registry = AttackMemoryRegistry(
            mode=contract.eval_plan.attack_memory,
            max_entries=contract.eval_plan.attack_memory_max_entries,
            shared_memory=shared_seed,
            capture_adapter=attack_capture_adapter,
        )
    tracker = _RunningStatsTracker.from_dict(
        threshold=contract.scoring.adversarial_failure_threshold,
        payload=(resumed_state or {}).get("metrics"),
    )

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
        plan = list(
            _lazy_weighted_plan(
                contract, persona_filter, scenario_filter, adversarial_filter
            )
        )
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
        planned["sequence"] = idx

    full_plan = list(plan)
    planned_conversations_total = len(plan)
    if completed_conversation_ids:
        plan = [
            p for p in plan if p["conversation_id"] not in completed_conversation_ids
        ]

    normalized_contract = contract_to_dict(contract)
    serialized_plan = _serialize_plan(full_plan)
    contract_fingerprint = _fingerprint_payload(normalized_contract)
    plan_fingerprint = _fingerprint_payload(serialized_plan)
    if resumed_state is not None:
        _validate_resume_fingerprints(
            resumed_state,
            contract_fingerprint=contract_fingerprint,
            plan_fingerprint=plan_fingerprint,
        )
    writer.write_json("contract.normalized.json", normalized_contract)
    writer.write_json("run_plan.json", serialized_plan)

    if not resume_incomplete:
        write_run_state(
            writer.run_dir,
            {
                "version": 2,
                "mode": "unified",
                "status": "in_progress",
                "run_id": run_id,
                "started_at": started_at,
                "updated_at": now_iso(),
                "total_planned_conversations": planned_conversations_total,
                "completed_conversations": 0,
                "completed_conversation_ids": [],
                "metrics": tracker.to_dict(),
                "meter": meter.snapshot(),
                "attack_memory": memory_registry.to_dict(),
                "contract_fingerprint": contract_fingerprint,
                "plan_fingerprint": plan_fingerprint,
            },
        )

    progress_total: int | None
    if budget_mode:
        progress_total = contract.eval_plan.total_conversations
    else:
        progress_total = len(plan)
    if progress_sink is not None:
        progress_sink(
            {
                "phase": "running",
                "completed": len(completed_conversation_ids),
                "total": progress_total,
                "last_item": None,
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "details": {
                    "remaining": (progress_total - len(completed_conversation_ids))
                    if progress_total is not None
                    else None,
                },
            }
        )
    progress = _RunProgressTracker(
        total=progress_total, enabled=not realtime_chat, progress_sink=progress_sink
    )
    processed_conversation_ids = set(completed_conversation_ids)
    personas_by_id = contract.persona_by_id()
    scenarios_by_id = contract.scenario_by_id()
    adversarial_by_id = contract.adversarial_by_id()
    persona_memory_actors = {
        persona_id: PersonaMemoryActor(
            persona=personas_by_id[persona_id],
            markdown_path=writer.persona_memory_path(persona_id),
            capture_adapter=persona_capture_adapter,
        )
        for persona_id in sorted({planned["persona_id"] for planned in full_plan})
    }
    await asyncio.gather(*(actor.start() for actor in persona_memory_actors.values()))

    async def _persist_result(
        sequence: int,
        persona_id: str,
        res: ConversationResult,
    ) -> None:
        await asyncio.to_thread(
            _append_result_to_artifacts, writer, res, output_conversations
        )
        memory_registry.commit(persona_id, res.memory_session)
        tracker.update(res)
        processed_conversation_ids.add(
            str(res.conversation_row.get("conversation_id") or "")
        )
        await asyncio.to_thread(
            write_run_state,
            writer.run_dir,
            {
                "version": 2,
                "mode": "unified",
                "status": "in_progress",
                "run_id": run_id,
                "started_at": started_at,
                "updated_at": now_iso(),
                "total_planned_conversations": planned_conversations_total,
                "completed_conversations": len(
                    [cid for cid in processed_conversation_ids if cid]
                ),
                "completed_conversation_ids": sorted(
                    [cid for cid in processed_conversation_ids if cid]
                ),
                "metrics": tracker.to_dict(),
                "meter": meter.snapshot(),
                "attack_memory": memory_registry.to_dict(),
                "contract_fingerprint": contract_fingerprint,
                "plan_fingerprint": plan_fingerprint,
            },
        )

    artifact_actor = ArtifactActor(_persist_result)

    effective_max_concurrency = (
        1
        if sequential
        else (max_concurrency_override or _effective_max_concurrency(contract))
    )
    if realtime_chat and persona_filter:
        effective_max_concurrency = 1
    semaphore = asyncio.Semaphore(max(1, effective_max_concurrency))

    if not realtime_chat:
        skipped_conversations = planned_conversations_total - len(plan)
        logger.info(
            "Starting %d conversations with max_concurrency=%d (already completed=%d, skipped=%d)",
            len(plan),
            effective_max_concurrency,
            len(completed_conversation_ids),
            skipped_conversations,
        )

    # Build interactive realtime controller if requested.
    realtime_controller: RealtimeChatController | None = None
    if realtime_chat and interactive_realtime_controls:
        personas_dict = contract.persona_by_id()
        single_persona_mode = (len(personas_dict) <= 1) or (persona_filter is not None)
        persona_total_convos: dict[str, int] = {}
        for p in plan:
            persona_total_convos[p["persona_id"]] = (
                persona_total_convos.get(p["persona_id"], 0) + 1
            )
        realtime_controller = RealtimeChatController(
            personas=personas_dict,
            single_persona_mode=single_persona_mode,
            persona_total_convos=persona_total_convos,
            status_provider=realtime_status_provider,
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
        start_async = getattr(realtime_controller, "start_async", None)
        if callable(start_async):
            await start_async()
        else:
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
                conversation_llms = {
                    name: provided.for_conversation(
                        make_conversation_rng(
                            contract.run.random_seed,
                            f"{planned['conversation_key']}:{name}",
                        ).getrandbits(32)
                    )
                    for name, provided in llms.items()
                }
                memory_snapshot = await persona_memory_actors[
                    planned["persona_id"]
                ].snapshot()
                res = await run_conversation(
                    entry=planned["entry"],
                    persona=personas_by_id[planned["persona_id"]],
                    synth_scenario=scenarios_by_id[planned["synth_scenario_id"]],
                    adv_scenario=adversarial_by_id[planned["adversarial_scenario_id"]],
                    contract=contract,
                    llms=conversation_llms,
                    target=target,
                    conversation_id=planned["conversation_id"],
                    rng=make_conversation_rng(
                        contract.run.random_seed, planned["conversation_key"]
                    ),
                    token_budget=token_budget,
                    attack_memory=memory_registry.for_persona(planned["persona_id"]),
                    persona_memory_snapshot=memory_snapshot,
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
                res = _failed_conversation_result(
                    planned=planned,
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=round(time.perf_counter() - started, 2),
                )
            finally:
                token_budget.release_reservations_for_prefix(
                    f"{planned['conversation_id']}:"
                )

            if res.termination_reason == "budget_exhausted" and not res.chat_history:
                return

            if res.persona_memory_delta is not None:
                await persona_memory_actors[planned["persona_id"]].commit(
                    planned["conversation_id"],
                    planned["sequence"],
                    res.persona_memory_delta,
                )

            await artifact_actor.submit(planned["sequence"], planned["persona_id"], res)
            await progress.mark_completed(planned["conversation_id"])

    budget_stopped = False
    start_time = time.time()
    try:
        await _run_sliding_window(
            plan,
            worker=_one,
            max_concurrency=effective_max_concurrency,
            can_admit=lambda: (
                not (realtime_controller and realtime_controller.stop_requested)
                and token_budget.can_continue(contract.run.reserve_tokens)
            ),
        )
        budget_stopped = bool(
            (realtime_controller and realtime_controller.stop_requested)
            or not token_budget.can_continue(contract.run.reserve_tokens)
        )
    finally:
        if realtime_controller:
            stop_async = getattr(realtime_controller, "stop_async", None)
            if callable(stop_async):
                await stop_async()
            else:
                realtime_controller.stop()
        await artifact_actor.close()
        await asyncio.gather(
            *(actor.close() for actor in persona_memory_actors.values())
        )
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
        tracker=tracker,
        plan=plan,
        run_id=run_id,
        dry_run=dry_run,
        memory_registry=memory_registry,
        output_conversations=output_conversations,
        meter=meter,
        budget_stopped=budget_stopped,
        elapsed_seconds=elapsed_seconds,
        effective_max_concurrency=effective_max_concurrency,
        planned_conversations_total=planned_conversations_total,
    )
    write_run_state(
        writer.run_dir,
        {
            "version": 2,
            "mode": "unified",
            "status": "completed",
            "run_id": run_id,
            "started_at": started_at,
            "updated_at": now_iso(),
            "completed_at": now_iso(),
            "total_planned_conversations": planned_conversations_total,
            "completed_conversations": len(
                [cid for cid in processed_conversation_ids if cid]
            ),
            "completed_conversation_ids": sorted(
                [cid for cid in processed_conversation_ids if cid]
            ),
            "metrics": tracker.to_dict(),
            "meter": meter.snapshot(),
            "attack_memory": memory_registry.to_dict(),
            "contract_fingerprint": contract_fingerprint,
            "plan_fingerprint": plan_fingerprint,
            "summary": summary,
        },
    )
    return summary


class _RunningStatsTracker:
    def __init__(self, threshold: int):
        self.threshold = threshold
        self.total_conversations = 0
        self.total_turns = 0
        self.synth_turns = 0
        self.adv_turns = 0
        self.errors = 0

        self.max_failure_score = 0
        self.failures_at_threshold = 0
        self.partials = 0  # adversarial turns with 0 < failure_score < threshold

        self.failure_scores: list[float] = []
        self.turns_to_failure: list[int] = []
        self.trace_severity_scores: list[float] = []
        self.trajectory_signal_sessions = 0
        self.failure_surface_counts: dict[str, int] = {}
        self.attack_angle_counts: dict[str, int] = {}
        self.attack_sub_tactic_counts: dict[str, int] = {}
        self.attack_skill_counts: dict[str, int] = {}
        self.attack_tool_counts: dict[str, int] = {}
        self.attack_tool_successes = 0
        self.attack_tool_errors = 0
        self.skill_execution_errors = 0

        self.synth_safety_scores: list[float] = []
        self.synth_relevance_scores: list[float] = []
        self.synth_groundedness_scores: list[float] = []

        self.chatbot_prompt_tokens = 0
        self.chatbot_completion_tokens = 0

        self.target_latencies_ms: list[float] = []
        self.conversation_elapsed_seconds: list[float] = []
        self.conversation_target_seconds: list[float] = []

    @classmethod
    def from_dict(
        cls, *, threshold: int, payload: dict[str, Any] | None
    ) -> _RunningStatsTracker:
        tracker = cls(threshold)
        if not payload:
            return tracker

        tracker.total_conversations = int(payload.get("total_conversations") or 0)
        tracker.total_turns = int(payload.get("total_turns") or 0)
        tracker.synth_turns = int(payload.get("synth_turns") or 0)
        tracker.adv_turns = int(payload.get("adv_turns") or 0)
        tracker.errors = int(payload.get("errors") or 0)
        tracker.max_failure_score = int(payload.get("max_failure_score") or 0)
        tracker.failures_at_threshold = int(payload.get("failures_at_threshold") or 0)
        # back-compat: older checkpoints stored this as "near_misses"
        tracker.partials = int(
            payload.get("partials", payload.get("near_misses", 0)) or 0
        )

        tracker.failure_scores = [float(v) for v in payload.get("failure_scores") or []]
        tracker.turns_to_failure = [
            int(v) for v in payload.get("turns_to_failure") or []
        ]
        tracker.trace_severity_scores = [
            float(v) for v in payload.get("trace_severity_scores") or []
        ]
        tracker.trajectory_signal_sessions = int(
            payload.get("trajectory_signal_sessions", 0) or 0
        )
        tracker.failure_surface_counts = {
            str(key): int(value)
            for key, value in (payload.get("failure_surface_counts") or {}).items()
        }
        tracker.attack_angle_counts = {
            str(key): int(value)
            for key, value in (payload.get("attack_angle_counts") or {}).items()
        }
        tracker.attack_sub_tactic_counts = {
            str(key): int(value)
            for key, value in (payload.get("attack_sub_tactic_counts") or {}).items()
        }
        tracker.attack_skill_counts = {
            str(key): int(value)
            for key, value in (payload.get("attack_skill_counts") or {}).items()
        }
        tracker.attack_tool_counts = {
            str(key): int(value)
            for key, value in (payload.get("attack_tool_counts") or {}).items()
        }
        tracker.attack_tool_successes = int(payload.get("attack_tool_successes") or 0)
        tracker.attack_tool_errors = int(payload.get("attack_tool_errors") or 0)
        tracker.skill_execution_errors = int(payload.get("skill_execution_errors") or 0)
        tracker.synth_safety_scores = [
            float(v) for v in payload.get("synth_safety_scores") or []
        ]
        tracker.synth_relevance_scores = [
            float(v) for v in payload.get("synth_relevance_scores") or []
        ]
        tracker.synth_groundedness_scores = [
            float(v) for v in payload.get("synth_groundedness_scores") or []
        ]
        tracker.chatbot_prompt_tokens = int(payload.get("chatbot_prompt_tokens") or 0)
        tracker.chatbot_completion_tokens = int(
            payload.get("chatbot_completion_tokens") or 0
        )
        tracker.target_latencies_ms = [
            float(v) for v in payload.get("target_latencies_ms") or []
        ]
        tracker.conversation_elapsed_seconds = [
            float(v) for v in payload.get("conversation_elapsed_seconds") or []
        ]
        tracker.conversation_target_seconds = [
            float(v) for v in payload.get("conversation_target_seconds") or []
        ]
        return tracker

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_conversations": self.total_conversations,
            "total_turns": self.total_turns,
            "synth_turns": self.synth_turns,
            "adv_turns": self.adv_turns,
            "errors": self.errors,
            "max_failure_score": self.max_failure_score,
            "failures_at_threshold": self.failures_at_threshold,
            "partials": self.partials,
            "failure_scores": self.failure_scores,
            "turns_to_failure": self.turns_to_failure,
            "trace_severity_scores": self.trace_severity_scores,
            "trajectory_signal_sessions": self.trajectory_signal_sessions,
            "failure_surface_counts": self.failure_surface_counts,
            "attack_angle_counts": self.attack_angle_counts,
            "attack_sub_tactic_counts": self.attack_sub_tactic_counts,
            "attack_skill_counts": self.attack_skill_counts,
            "attack_tool_counts": self.attack_tool_counts,
            "attack_tool_successes": self.attack_tool_successes,
            "attack_tool_errors": self.attack_tool_errors,
            "skill_execution_errors": self.skill_execution_errors,
            "synth_safety_scores": self.synth_safety_scores,
            "synth_relevance_scores": self.synth_relevance_scores,
            "synth_groundedness_scores": self.synth_groundedness_scores,
            "chatbot_prompt_tokens": self.chatbot_prompt_tokens,
            "chatbot_completion_tokens": self.chatbot_completion_tokens,
            "target_latencies_ms": self.target_latencies_ms,
            "conversation_elapsed_seconds": self.conversation_elapsed_seconds,
            "conversation_target_seconds": self.conversation_target_seconds,
        }

    def update(self, res: ConversationResult) -> None:
        self.total_conversations += 1
        self.total_turns += len(res.turn_rows)
        self.synth_turns += res.conversation_row["synth_turns"]
        self.adv_turns += res.conversation_row["adversarial_turns"]
        self.errors += res.errors

        best_failure = res.conversation_row["best_failure_score"]
        self.max_failure_score = max(self.max_failure_score, best_failure)
        if bool(res.conversation_row.get("is_breach", best_failure >= self.threshold)):
            self.failures_at_threshold += 1
            self.turns_to_failure.append(res.conversation_row["adversarial_turns"])

        adversarial_score_rows = [
            row for row in res.score_rows if row.get("turn_type") == "adversarial"
        ]
        if not adversarial_score_rows:
            # Backward compatibility for v1 checkpoints/tests whose score rows did
            # not carry adversarial outcomes.
            adversarial_score_rows = [
                row for row in res.turn_rows if row.get("turn_type") == "adversarial"
            ]
        conversation_has_trajectory_signal = False
        for row in adversarial_score_rows:
            if row.get("turn_type") == "adversarial":
                fail_score = row.get("failure_score")
                if isinstance(fail_score, (int, float)):
                    self.failure_scores.append(fail_score)
                    effective = row.get("effective_failure_score", fail_score)
                    row_threshold = row.get("failure_threshold", self.threshold)
                    if (
                        isinstance(effective, (int, float))
                        and isinstance(row_threshold, (int, float))
                        and 0 < effective < row_threshold
                    ):
                        self.partials += 1
                trace_score = row.get("trace_severity_score")
                if isinstance(trace_score, (int, float)) and trace_score > 0:
                    self.trace_severity_scores.append(trace_score)
                    conversation_has_trajectory_signal = True
                surface = row.get("failure_surface")
                if isinstance(surface, str) and surface and surface != "none":
                    self.failure_surface_counts[surface] = (
                        self.failure_surface_counts.get(surface, 0) + 1
                    )
        if conversation_has_trajectory_signal:
            self.trajectory_signal_sessions += 1

        for row in res.score_rows:
            if row.get("turn_type") == "synth":
                safety = row.get("safety_score")
                relevance = row.get("relevance_score")
                groundedness = row.get("groundedness_score")
                if isinstance(safety, (int, float)):
                    self.synth_safety_scores.append(safety)
                if isinstance(relevance, (int, float)):
                    self.synth_relevance_scores.append(relevance)
                if isinstance(groundedness, (int, float)):
                    self.synth_groundedness_scores.append(groundedness)

        for row in res.turn_rows:
            if row.get("turn_type") != "adversarial":
                continue
            metadata = row.get("generation_metadata")
            strategy = (
                metadata.get("strategy", {}) if isinstance(metadata, dict) else {}
            )
            if not isinstance(strategy, dict):
                strategy = {}
            angle = strategy.get("attack_angle")
            if isinstance(angle, str) and angle:
                self.attack_angle_counts[angle] = (
                    self.attack_angle_counts.get(angle, 0) + 1
                )
            sub_tactic = strategy.get("sub_tactic")
            if isinstance(sub_tactic, str) and sub_tactic:
                self.attack_sub_tactic_counts[sub_tactic] = (
                    self.attack_sub_tactic_counts.get(sub_tactic, 0) + 1
                )
            skill_name = strategy.get("skill_name", row.get("skill_name"))
            skill_version = strategy.get("skill_version", row.get("skill_version"))
            if isinstance(skill_name, str) and skill_name:
                skill_key = (
                    f"{skill_name}@{skill_version}"
                    if isinstance(skill_version, str) and skill_version
                    else skill_name
                )
                self.attack_skill_counts[skill_key] = (
                    self.attack_skill_counts.get(skill_key, 0) + 1
                )
            events = strategy.get("skill_tool_events", row.get("skill_tool_events", []))
            if isinstance(events, list):
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    tool_name = event.get("tool")
                    if isinstance(tool_name, str) and tool_name:
                        self.attack_tool_counts[tool_name] = (
                            self.attack_tool_counts.get(tool_name, 0) + 1
                        )
                    if event.get("status") == "success":
                        self.attack_tool_successes += 1
                    elif event.get("status") == "error":
                        self.attack_tool_errors += 1
            if row.get("skill_execution_error"):
                self.skill_execution_errors += 1

        for rec in res.chat_history:
            if rec.generation_metadata:
                self.chatbot_prompt_tokens += rec.generation_metadata.get(
                    "chatbot_prompt_tokens", 0
                )
                self.chatbot_completion_tokens += rec.generation_metadata.get(
                    "chatbot_completion_tokens", 0
                )

        # Performance stats
        for row in res.turn_rows:
            latency = row.get("latency_ms")
            if isinstance(latency, (int, float)):
                self.target_latencies_ms.append(latency)

        elapsed = res.conversation_row.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)):
            self.conversation_elapsed_seconds.append(elapsed)

        target_latency_seconds = res.conversation_row.get("target_latency_seconds")
        if isinstance(target_latency_seconds, (int, float)):
            self.conversation_target_seconds.append(target_latency_seconds)


def _append_result_to_artifacts(
    writer: UnifiedArtifactWriter,
    res: ConversationResult,
    output_conversations: bool,
) -> None:
    """Append a single conversation's outputs to the artifact files in real time."""
    writer.append_jsonl("conversations.jsonl", [res.conversation_row])
    if res.turn_rows:
        writer.append_jsonl("turns.jsonl", res.turn_rows)
    if res.score_rows:
        writer.append_jsonl("scores.jsonl", res.score_rows)
    if res.failed_rows:
        writer.append_jsonl("failed_examples.jsonl", res.failed_rows)
    if res.adversarial_session:
        writer.append_jsonl("adversarial_sessions.jsonl", [res.adversarial_session])
    if res.chat_history:
        rows = [record.to_dict() for record in res.chat_history]
        writer.append_chat_history_rows(rows, overwrite=False)
        if output_conversations:
            writer.append_conversation_txt(res.chat_history, overwrite=False)


def _ensure_progressive_artifacts_exist(
    *, writer: UnifiedArtifactWriter, output_conversations: bool
) -> None:
    required_jsonl = (
        "conversations.jsonl",
        "turns.jsonl",
        "scores.jsonl",
        "failed_examples.jsonl",
        "adversarial_sessions.jsonl",
        "chat_history.jsonl",
    )
    for name in required_jsonl:
        path = writer.run_dir / name
        if not path.exists():
            writer.write_jsonl(name, [])

    csv_path = writer.run_dir / "chat_history.csv"
    if not csv_path.exists():
        writer._write_csv("chat_history.csv", [], append=False)

    if output_conversations:
        conv_txt = writer.run_dir / "conversations.txt"
        if not conv_txt.exists():
            conv_txt.write_text("", encoding="utf-8")


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

    personas_by_lower = {
        p.persona_id.lower(): p.persona_id for p in contract.persona_pool
    }
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
        entries = [
            e for e in entries if e.adversarial_scenario_id == adversarial_filter
        ]
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
        entries = [
            e for e in entries if e.adversarial_scenario_id == adversarial_filter
        ]
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
        range(len(entries)),
        key=lambda i: raw[i] - counts[i],
        reverse=True,
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
            plan.append(
                {
                    "entry": entry,
                    "persona_id": entry.persona_id,
                    "synth_scenario_id": entry.synth_scenario_id,
                    "adversarial_scenario_id": entry.adversarial_scenario_id,
                    "turn_count": int(turn_count),
                    "conversation_key": f"{entry.persona_id}:{entry.synth_scenario_id}:{entry.adversarial_scenario_id}:{k}",
                }
            )
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
            "best_effective_failure_score": 0,
            "failure_threshold": 0,
            "is_breach": False,
            "termination_reason": "runner_exception",
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
        termination_reason="runner_exception",
    )


def _force_mock_providers(contract: UnifiedContract) -> UnifiedContract:
    """For --dry-run: replace top-level llm with mock; clear per-component overrides.
    Target LLM (if any) is also mocked so no API key is required.
    """
    from adaptive_synth_eval.unified_eval.config.schemas import (
        ComponentOverrides,
        LLMSpec,
    )
    from adaptive_synth_eval.unified_eval.config.schemas import (
        UnifiedContract as _UC,
    )

    mock_spec = LLMSpec(
        provider="mock", model="mock", max_tokens=contract.llm.max_tokens
    )
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
        target_llm=(
            LLMSpec(provider="mock", model="mock") if contract.target_llm else None
        ),
        target_system_prompt=contract.target_system_prompt,
        trajectory=contract.trajectory,
        attack_skills=contract.attack_skills,
        warnings=list(contract.warnings) + ["dry_run: forced mock LLM providers"],
    )


def _persist_and_summarize(
    *,
    contract: UnifiedContract,
    writer: UnifiedArtifactWriter,
    tracker: _RunningStatsTracker,
    plan: list[dict[str, Any]],
    run_id: str,
    dry_run: bool,
    memory_registry: AttackMemoryRegistry,
    output_conversations: bool = False,
    meter: BudgetMeter | None = None,
    budget_stopped: bool = False,
    elapsed_seconds: float = 0.0,
    effective_max_concurrency: int = 1,
    planned_conversations_total: int | None = None,
) -> dict[str, Any]:
    errors = tracker.errors
    synth_turns = tracker.synth_turns
    adv_turns = tracker.adv_turns
    max_failure = tracker.max_failure_score
    failures_at_threshold = tracker.failures_at_threshold
    partials = tracker.partials

    # Failure percentiles (p50/p90/p95) — surface "how close" attacks got, not just the binary count.
    threshold = contract.scoring.adversarial_failure_threshold
    failure_percentiles = {
        "failure_score": _percentiles(tracker.failure_scores),
        "turns_to_failure": _percentiles(tracker.turns_to_failure),
    }

    mean_safety = _mean(tracker.synth_safety_scores)
    mean_relevance = _mean(tracker.synth_relevance_scores)
    mean_grounded = _mean(tracker.synth_groundedness_scores)

    if memory_registry.mode != "none":
        writer.write_attack_memory(memory_registry.to_dict())

    budget_summary = (
        meter.summary(stopped_due_to_budget=budget_stopped)
        if meter is not None
        else None
    )
    planner_usage: dict[str, Any] = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    if budget_summary is not None:
        for component in budget_summary.get("per_component", []):
            if component.get("component") == "planner":
                planner_usage = {
                    key: component.get(key, 0)
                    for key in (
                        "calls",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                    )
                }
                break

    attack_methods = {
        "skills_enabled": contract.attack_skills.enabled,
        "angle_counts": dict(sorted(tracker.attack_angle_counts.items())),
        "sub_tactic_counts": dict(sorted(tracker.attack_sub_tactic_counts.items())),
        "skill_counts": dict(sorted(tracker.attack_skill_counts.items())),
        "unique_angles": len(tracker.attack_angle_counts),
        "unique_sub_tactics": len(tracker.attack_sub_tactic_counts),
        "tool_utilization": {
            "calls": sum(tracker.attack_tool_counts.values()),
            "successes": tracker.attack_tool_successes,
            "errors": tracker.attack_tool_errors,
            "by_tool": dict(sorted(tracker.attack_tool_counts.items())),
        },
        "skill_execution_errors": tracker.skill_execution_errors,
        "planner_usage": planner_usage,
    }

    # Calculate token usage statistics from meter (simulator tokens only)
    simulator_prompt_tokens = 0
    simulator_completion_tokens = 0
    if meter is not None:
        sim_meter = meter.components.get("user_simulator")
        if sim_meter is not None:
            simulator_prompt_tokens = sim_meter.prompt_tokens
            simulator_completion_tokens = sim_meter.completion_tokens
    simulator_total_tokens = simulator_prompt_tokens + simulator_completion_tokens

    convo_count = tracker.total_conversations
    avg_prompt_tokens_convo = (
        round(simulator_prompt_tokens / convo_count, 2) if convo_count else 0.0
    )
    avg_completion_tokens_convo = (
        round(simulator_completion_tokens / convo_count, 2) if convo_count else 0.0
    )
    avg_total_tokens_convo = (
        round(simulator_total_tokens / convo_count, 2) if convo_count else 0.0
    )

    # Calculate estimated chatbot token usage
    chatbot_prompt_tokens = tracker.chatbot_prompt_tokens
    chatbot_completion_tokens = tracker.chatbot_completion_tokens
    chatbot_total_tokens = chatbot_prompt_tokens + chatbot_completion_tokens

    avg_chatbot_prompt_tokens_convo = (
        round(chatbot_prompt_tokens / convo_count, 2) if convo_count else 0.0
    )
    avg_chatbot_completion_tokens_convo = (
        round(chatbot_completion_tokens / convo_count, 2) if convo_count else 0.0
    )
    avg_chatbot_total_tokens_convo = (
        round(chatbot_total_tokens / convo_count, 2) if convo_count else 0.0
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

    target_latencies_ms = tracker.target_latencies_ms
    conversation_elapsed_seconds = tracker.conversation_elapsed_seconds
    conversation_target_seconds = tracker.conversation_target_seconds
    performance_stats = {
        "target_latency_total_seconds": round(sum(target_latencies_ms) / 1000, 2)
        if target_latencies_ms
        else 0.0,
        "avg_target_latency_per_turn_seconds": round(
            sum(target_latencies_ms) / len(target_latencies_ms) / 1000, 2
        )
        if target_latencies_ms
        else 0.0,
        "max_target_latency_per_turn_seconds": round(max(target_latencies_ms) / 1000, 2)
        if target_latencies_ms
        else 0.0,
        "avg_conversation_elapsed_seconds": round(
            sum(conversation_elapsed_seconds) / len(conversation_elapsed_seconds), 2
        )
        if conversation_elapsed_seconds
        else 0.0,
        "max_conversation_elapsed_seconds": round(max(conversation_elapsed_seconds), 2)
        if conversation_elapsed_seconds
        else 0.0,
        "avg_target_latency_per_conversation_seconds": round(
            sum(conversation_target_seconds) / len(conversation_target_seconds), 2
        )
        if conversation_target_seconds
        else 0.0,
    }

    # Scale Projections
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
        scale_projections.update(
            {
                "steady_state_conversations_per_second": round(steady_rate, 4),
                "steady_state_time_for_1k_conversations_seconds": round(
                    1000 / steady_rate, 2
                ),
                "steady_state_time_for_10k_conversations_seconds": round(
                    10000 / steady_rate, 2
                ),
                "steady_state_time_for_100k_conversations_seconds": round(
                    100000 / steady_rate, 2
                ),
            }
        )

    summary = {
        "run_id": run_id,
        "total_conversations": convo_count,
        "planned_conversations": planned_conversations_total or convo_count,
        "total_turns": tracker.total_turns,
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
        "partials": partials,
        "failure_percentiles": failure_percentiles,
        "attack_methods": attack_methods,
        "mean_safety_score": mean_safety,
        "mean_relevance_score": mean_relevance,
        "mean_groundedness_score": mean_grounded,
        "budget": budget_summary,
        "tokens": tokens_stats,
        "performance": performance_stats,
        "scale_projections": scale_projections,
    }
    if contract.trajectory.enabled:
        summary["trajectory"] = {
            "max_trace_severity_score": (
                max(tracker.trace_severity_scores)
                if tracker.trace_severity_scores
                else 0
            ),
            "mean_trace_severity_score": _mean(tracker.trace_severity_scores),
            "sessions_with_signal": tracker.trajectory_signal_sessions,
            "failure_surface_counts": dict(
                sorted(tracker.failure_surface_counts.items())
            ),
        }
    writer.write_unified_summary(summary)
    writer.write_unified_report(summary)
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
        rows.append(
            {
                "persona_id": p["persona_id"],
                "conversation_id": p["conversation_id"],
                "synth_scenario_id": p["synth_scenario_id"],
                "adversarial_scenario_id": p["adversarial_scenario_id"],
                "turn_count": p["turn_count"],
                "conversation_key": p["conversation_key"],
                "weight": p["entry"].weight,
                "schedule": p["entry"].schedule.__dict__,
                "synth_to_adversarial_ratio": p["entry"].synth_to_adversarial_ratio,
            }
        )
    return rows


def _estimate_remaining_seconds(
    *, completed: int, total: int | None, elapsed_seconds: float
) -> float | None:
    if total is None:
        return None
    if completed <= 0 or elapsed_seconds <= 0:
        return None
    remaining = max(total - completed, 0)
    rate = completed / elapsed_seconds
    if rate <= 0:
        return None
    return remaining / rate


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_eta_timestamp(eta_seconds: float | None) -> str:
    if eta_seconds is None:
        return "unknown"
    eta_dt = datetime.now().astimezone() + timedelta(seconds=max(0.0, eta_seconds))
    return eta_dt.isoformat(timespec="seconds")


def _now_iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
