from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import yaml

from adaptive_synth_eval.config.env import (
    load_project_env,
    resolve_env_placeholders,
)
from adaptive_synth_eval.file_lock import file_lock
from adaptive_synth_eval.adversarial_response_engine.engine.taxonomy import (
    ANGLE_NAMES,
)
from adaptive_synth_eval.learning.candidates import (
    CandidateGenerator,
    CandidateValidator,
)
from adaptive_synth_eval.learning.experience import (
    ExperienceBuilder,
    artifact_fingerprint,
)
from adaptive_synth_eval.learning.models import LearningBundle
from adaptive_synth_eval.learning.registry import LearningRegistry
from adaptive_synth_eval.learning.tournament import (
    PromotionVerifier,
    TournamentRunner,
    render_evidence_report,
)
from adaptive_synth_eval.loop.planner import LoopReasoner
from adaptive_synth_eval.loop.profiles import LoopProfile
from adaptive_synth_eval.unified_eval.config.contract import (
    contract_to_dict,
    load_unified_contract,
)
from adaptive_synth_eval.unified_eval.orchestrator.runner import run_unified


TournamentExecute = Callable[
    [str, LearningBundle, int, str, str | None], dict[str, Any]
]


class LearningCoordinator:
    def __init__(
        self,
        profile: LoopProfile,
        *,
        output_dir: str | Path,
        tournament_execute: TournamentExecute | None = None,
        proposal_fn: Callable[[str], str] | None = None,
        target_fingerprint_override: str | None = None,
        bootstrap_samples: int = 1000,
    ) -> None:
        self.profile = profile
        self.output_dir = Path(output_dir)
        self._registry: LearningRegistry | None = None
        self._proposal_fn = proposal_fn
        self._target_fingerprint_override = target_fingerprint_override
        self.bootstrap_samples = bootstrap_samples
        self._tournament_execute = tournament_execute

    @property
    def registry(self) -> LearningRegistry:
        if self._registry is None:
            self._registry = LearningRegistry(
                self.output_dir, self.profile.profile_id
            )
        return self._registry

    def status(self) -> dict[str, Any]:
        if not self.profile.learning.enabled:
            return {
                "profile_id": self.profile.profile_id,
                "status": "disabled",
                "active": None,
                "candidates": [],
            }
        candidates = self.registry.list_candidates()
        active = (
            json.loads(self.registry.active_path.read_text(encoding="utf-8"))
            if self.registry.active_path.exists()
            else None
        )
        ledger = ExperienceBuilder(
            self.output_dir, self.profile.profile_id
        ).read_records()
        return {
            "profile_id": self.profile.profile_id,
            "status": (
                "active"
                if active is not None
                else (
                    "candidates_pending"
                    if candidates
                    else "waiting_for_evidence"
                )
            ),
            "active": active,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "experience_runs": len(ledger),
            "adversarial_conversations": sum(
                int(item.get("adversarial_conversations") or 0)
                for item in ledger
            ),
        }

    def run(
        self, *, run_dirs: Iterable[str | Path] | None = None
    ) -> dict[str, Any]:
        if not self.profile.learning.enabled:
            return {
                "profile_id": self.profile.profile_id,
                "status": "disabled",
            }
        lock_root = (
            self.output_dir / "learning" / self.profile.profile_id
        )
        lock_root.mkdir(parents=True, exist_ok=True)
        with self._coordinator_lock(lock_root / ".coordinator.lock"):
            return self._run_locked(run_dirs=run_dirs)

    def _run_locked(
        self, *, run_dirs: Iterable[str | Path] | None
    ) -> dict[str, Any]:
        builder = ExperienceBuilder(self.output_dir, self.profile.profile_id)
        discovered = (
            list(run_dirs)
            if run_dirs is not None
            else self._discover_run_dirs()
        )
        mined = builder.mine(discovered)
        records = builder.read_records()
        consumed = self._consumed_run_ids()
        eligible = [
            record
            for record in records
            if str(record.get("run_id")) not in consumed
        ]
        conversations = sum(
            int(item.get("adversarial_conversations") or 0)
            for item in eligible
        )
        if (
            len(eligible) < self.profile.learning.min_new_runs
            or conversations
            < self.profile.learning.min_new_adversarial_conversations
        ):
            return {
                "profile_id": self.profile.profile_id,
                "status": "waiting_for_evidence",
                "eligible_runs": len(eligible),
                "eligible_adversarial_conversations": conversations,
                "mined": mined,
            }

        contract_path = self._base_contract_path()
        base_contract = self._load_contract_payload(contract_path)
        active = self.registry.active_bundle()
        validator = CandidateValidator(
            candidate_kinds=self.profile.learning.candidate_kinds
        )
        effective_base = (
            validator.validate(
                active.patch,
                base_contract=base_contract,
                base_path=contract_path.parent,
            )
            if active is not None
            else base_contract
        )
        proposal_fn = (
            self._proposal_fn
            if self._proposal_fn is not None
            else self._reasoning_proposal_fn()
        )
        generated = CandidateGenerator(
            proposal_fn=proposal_fn,
            validator=validator,
            candidate_kinds=self.profile.learning.candidate_kinds,
        ).generate(
            profile_id=self.profile.profile_id,
            parent_id=None if active is None else active.bundle_id,
            base_contract=effective_base,
            experiences=eligible,
        )
        cumulative_patch = (
            list(active.patch) + list(generated.patch)
            if active is not None
            else list(generated.patch)
        )
        policy = {
            **({} if active is None else active.policy),
            **generated.policy,
        }
        challenger_contract = validator.validate(
            cumulative_patch,
            base_contract=base_contract,
            base_path=contract_path.parent,
        )
        target_fingerprint = (
            self._target_fingerprint_override
            or artifact_fingerprint(
                contract_to_dict(load_unified_contract(contract_path))[
                    "target"
                ]
            )
        )
        challenger = LearningBundle.create(
            profile_id=self.profile.profile_id,
            parent_id=None if active is None else active.bundle_id,
            patch=cumulative_patch,
            policy=policy,
            provenance={
                **generated.provenance,
                "base_contract": str(contract_path),
                "base_contract_fingerprint": artifact_fingerprint(base_contract),
                "target_fingerprint": target_fingerprint,
                "eligible_runs": len(eligible),
                "eligible_adversarial_conversations": conversations,
            },
        )
        if (
            active is not None
            and challenger.patch == active.patch
            and challenger.policy == active.policy
        ):
            candidate = self.registry.create_candidate(challenger)
            self.registry.mark_evaluating(candidate["candidate_id"])
            self.registry.record_evaluation(
                candidate["candidate_id"],
                {
                    "verdict": "failed",
                    "reason": "Evidence produced no effective evaluator change.",
                    "pairs": 0,
                    "observations": [],
                    "target_fingerprint": target_fingerprint,
                },
            )
            return {
                "profile_id": self.profile.profile_id,
                "status": "no_candidate_change",
                "eligible_runs": len(eligible),
                "candidate_id": candidate["candidate_id"],
                "bundle_id": challenger.bundle_id,
            }
        candidate = self.registry.create_candidate(challenger)
        self.registry.mark_evaluating(candidate["candidate_id"])

        champion = active or LearningBundle.create(
            profile_id=self.profile.profile_id,
            parent_id=None,
            patch=[],
            policy={
                "ucb_exploration_c": 1.4,
                "minimum_trials_per_angle": 1,
            },
            provenance={"baseline_contract": str(contract_path)},
            created_at="baseline",
        )
        execute = self._tournament_execute or EvaluatorTournamentExecutor(
            self.profile,
            output_dir=self.output_dir,
            tournament_id=challenger.digest[:16],
        )
        promotion = self.profile.learning.promotion
        verifier = PromotionVerifier(
            novelty_weight=promotion.novelty_weight,
            coverage_weight=promotion.coverage_weight,
            max_detection_drop_points=promotion.max_detection_drop_points,
            max_judge_error_increase_points=(
                promotion.max_judge_error_increase_points
            ),
            max_token_cost_increase_ratio=(
                promotion.max_token_cost_increase_ratio
            ),
            bootstrap_samples=self.bootstrap_samples,
        )
        tournament = self.profile.learning.tournament
        try:
            evaluation = TournamentRunner(
                execute=execute,
                initial_pairs=tournament.initial_pairs,
                batch_pairs=tournament.batch_pairs,
                max_pairs=tournament.max_pairs,
                verifier=verifier,
            ).run(
                champion=champion,
                challenger=challenger,
                target_fingerprint=target_fingerprint,
                validation_contracts=(
                    self.profile.learning.validation_contracts
                ),
                enabled_taxonomy=self._structural_taxonomy(effective_base),
                challenger_taxonomy=self._structural_taxonomy(
                    challenger_contract
                ),
            )
        except Exception as exc:
            evaluation = {
                "verdict": "failed",
                "reason": (
                    "Tournament execution failed: "
                    f"{type(exc).__name__}: {str(exc)[:500]}"
                ),
                "pairs": 0,
                "observations": [],
                "target_fingerprint": target_fingerprint,
                "retryable": True,
            }
        self.registry.record_evaluation(
            candidate["candidate_id"], evaluation
        )
        report_path = (
            self.registry.candidates_dir
            / candidate["candidate_id"]
            / "evidence.md"
        )
        report_path.write_text(
            render_evidence_report(
                evaluation,
                champion_id=champion.bundle_id,
                challenger_id=challenger.bundle_id,
            ),
            encoding="utf-8",
        )
        return {
            "profile_id": self.profile.profile_id,
            "status": f"candidate_{evaluation['verdict']}",
            "candidate_id": candidate["candidate_id"],
            "bundle_id": challenger.bundle_id,
            "evaluation": evaluation,
            "evidence_report": str(report_path),
            "active_bundle": (
                None if active is None else active.bundle_id
            ),
        }

    @staticmethod
    @contextmanager
    def _coordinator_lock(path: Path) -> Iterator[None]:
        with file_lock(path):
            yield

    def show(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.registry.get_candidate(candidate_id)
        bundle = self.registry.bundle_for_candidate(candidate_id)
        return {**candidate, "bundle": bundle.to_dict()}

    def _discover_run_dirs(self) -> list[Path]:
        state_path = (
            self.output_dir
            / "loops"
            / "state"
            / f"{self.profile.profile_id}.json"
        )
        if not state_path.exists():
            return []
        state = json.loads(state_path.read_text(encoding="utf-8"))
        results: list[Path] = []
        for item in state.get("recent_runs") or []:
            if (
                item.get("mode") != "unified"
                or item.get("status") != "completed"
                or bool(item.get("dry_run"))
            ):
                continue
            output = item.get("output_dir")
            if output:
                results.append(Path(str(output)))
        return results

    def _consumed_run_ids(self) -> set[str]:
        consumed: set[str] = set()
        for candidate in self.registry.list_candidates():
            if candidate["status"] in {"draft", "evaluating"} or bool(
                (candidate.get("evaluation") or {}).get("retryable")
            ):
                continue
            bundle = self.registry.bundle_for_candidate(
                str(candidate["candidate_id"])
            )
            consumed.update(
                str(run_id)
                for run_id in bundle.provenance.get("run_ids") or []
            )
        return consumed

    @staticmethod
    def _structural_taxonomy(
        contract: dict[str, Any],
    ) -> dict[str, set[str]]:
        personas = {
            str(item.get("persona_id"))
            for item in (contract.get("persona_pool") or [])
            if isinstance(item, dict) and item.get("persona_id")
        }
        scenarios = {
            str(item.get("scenario_type"))
            for catalog in (
                contract.get("scenario_catalog") or [],
                contract.get("adversarial_scenario_catalog") or [],
            )
            for item in catalog
            if isinstance(item, dict) and item.get("scenario_type")
        }
        return {
            "personas": personas,
            "scenarios": scenarios,
            "angles": set(ANGLE_NAMES),
        }

    def _reasoning_proposal_fn(self) -> Callable[[str], str] | None:
        reasoner = LoopReasoner(self.profile)
        if reasoner.client is None:
            return None

        def propose(prompt: str) -> str:
            result = reasoner.client.complete(prompt)
            if result.error:
                return ""
            return result.content

        return propose

    def _base_contract_path(self) -> Path:
        for target in self.profile.targets:
            path = self._resolve_profile_path(target.contract)
            payload = self._load_contract_payload(path)
            if "suite" in payload and "eval_plan" in payload:
                return path
        raise ValueError(
            "Learning requires at least one unified target contract"
        )

    def _resolve_profile_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        current = self.profile.source_path.parent
        for candidate in (current, *current.parents):
            if (candidate / "pyproject.toml").exists():
                return (candidate / path).resolve()
        return (current / path).resolve()

    @staticmethod
    def _load_contract_payload(path: Path) -> dict[str, Any]:
        load_project_env(anchor=path, override=False)
        text = path.read_text(encoding="utf-8")
        payload = (
            json.loads(text)
            if path.suffix.lower() == ".json"
            else yaml.safe_load(text)
        )
        resolved = resolve_env_placeholders(payload)
        if not isinstance(resolved, dict):
            raise ValueError(f"Contract must be a mapping: {path}")
        return resolved


class EvaluatorTournamentExecutor:
    def __init__(
        self,
        profile: LoopProfile,
        *,
        output_dir: Path,
        tournament_id: str,
    ) -> None:
        self.profile = profile
        self.output_dir = output_dir
        self.tournament_id = tournament_id

    def _run_id(self, variant: str, pack: str, seed: int) -> str:
        return (
            f"learning-{self.tournament_id}-{variant}-{pack}-{seed:04d}"
        )

    def __call__(
        self,
        variant: str,
        bundle: LearningBundle,
        seed: int,
        pack: str,
        contract_ref: str | None,
    ) -> dict[str, Any]:
        coordinator = LearningCoordinator(
            self.profile, output_dir=self.output_dir
        )
        contract_path = (
            coordinator._resolve_profile_path(contract_ref)
            if contract_ref
            else coordinator._base_contract_path()
        )
        contract = load_unified_contract(
            contract_path, learning_bundle=bundle
        )
        run_id = self._run_id(variant, pack, seed)
        run = replace(
            contract.run,
            run_id=run_id,
            random_seed=seed,
            max_concurrency=1,
            until_budget_exhausted=False,
        )
        eval_plan = replace(contract.eval_plan, total_conversations=1)
        output = replace(
            contract.output,
            base_dir=(
                self.output_dir
                / "learning"
                / self.profile.profile_id
                / "tournament-runs"
            ),
            run_id=run_id,
        )
        contract = replace(
            contract,
            run=run,
            eval_plan=eval_plan,
            output=output,
        )
        summary = run_unified(
            contract,
            dry_run=False,
            max_concurrency_override=1,
            run_id_override=run_id,
        )
        run_dir = Path(str(summary["output_dir"]))
        record, reason = ExperienceBuilder(
            self.output_dir, self.profile.profile_id
        )._build_record(run_dir)
        if record is None:
            raise ValueError(
                f"Tournament run {run_id} is ineligible: {reason}"
            )
        coverage = record.get("coverage") or {}
        return {
            "variant": variant,
            "seed": seed,
            "pack": pack,
            "failure_signatures": [
                item["signature"]
                for item in record.get("failure_signatures") or []
            ],
            "detected": bool(record.get("failure_signatures")),
            "judge_error": bool(record.get("judge_errors")),
            "tokens": int(record.get("total_tokens") or 0),
            "coverage": {
                dimension: [
                    category
                    for category, count in (coverage.get(dimension) or {}).items()
                    for _ in range(int(count))
                ]
                for dimension in ("personas", "scenarios", "angles")
            },
            "target_fingerprint": record["target_fingerprint"],
            "run_id": record["run_id"],
            "run_dir": str(run_dir),
        }
