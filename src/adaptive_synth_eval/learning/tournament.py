from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

from adaptive_synth_eval.learning.models import LearningBundle


Pair = tuple[dict[str, Any], dict[str, Any]]


class PromotionVerifier:
    def __init__(
        self,
        *,
        novelty_weight: float = 0.7,
        coverage_weight: float = 0.3,
        max_detection_drop_points: float = 5.0,
        max_judge_error_increase_points: float = 1.0,
        max_token_cost_increase_ratio: float = 0.2,
        bootstrap_samples: int = 1000,
    ) -> None:
        self.novelty_weight = novelty_weight
        self.coverage_weight = coverage_weight
        self.max_detection_drop_points = max_detection_drop_points
        self.max_judge_error_increase_points = (
            max_judge_error_increase_points
        )
        self.max_token_cost_increase_ratio = max_token_cost_increase_ratio
        self.bootstrap_samples = max(1, bootstrap_samples)

    def evaluate(
        self,
        pairs: list[Pair],
        *,
        enabled_taxonomy: dict[str, set[str]] | None = None,
        challenger_taxonomy: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        champion = [pair[0] for pair in pairs]
        challenger = [pair[1] for pair in pairs]
        champion_metrics = self._metrics(champion)
        challenger_metrics = self._metrics(challenger)
        score_delta = challenger_metrics["score"] - champion_metrics["score"]
        additional = sorted(
            set(challenger_metrics["reproducible_signatures"])
            - set(champion_metrics["reproducible_signatures"])
        )
        confidence = self._paired_confidence_interval(pairs)
        gate_failures = self._gate_failures(
            champion_metrics,
            challenger_metrics,
            enabled_taxonomy=enabled_taxonomy,
            challenger_taxonomy=challenger_taxonomy,
        )

        if gate_failures:
            verdict = "failed"
            reason = "; ".join(gate_failures)
        elif additional and confidence[0] > 0:
            verdict = "passed"
            reason = "Challenger has positive paired evidence and passes all gates."
        else:
            verdict = "inconclusive"
            reason = (
                "Evidence does not yet establish a positive challenger advantage."
            )
        return {
            "verdict": verdict,
            "reason": reason,
            "score_delta": score_delta,
            "confidence_interval": confidence,
            "additional_reproducible_signatures": additional,
            "gate_failures": gate_failures,
            "champion": champion_metrics,
            "challenger": challenger_metrics,
        }

    def _metrics(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        fresh = [item for item in observations if item.get("pack") == "fresh"]
        locked = [
            item for item in observations if item.get("pack") == "locked"
        ]
        signature_seeds: dict[str, set[int]] = defaultdict(set)
        for item in fresh:
            seed = int(item.get("seed") or 0)
            for signature in item.get("failure_signatures") or []:
                signature_seeds[str(signature)].add(seed)
        reproducible = sorted(
            signature
            for signature, seeds in signature_seeds.items()
            if len(seeds) >= 2
        )
        novelty_rate = len(reproducible) / max(1, len(fresh))

        coverage_counts: dict[str, Counter[str]] = {
            "personas": Counter(),
            "scenarios": Counter(),
            "angles": Counter(),
        }
        for item in observations:
            coverage = item.get("coverage") or {}
            for dimension in coverage_counts:
                value = coverage.get(dimension)
                if isinstance(value, list):
                    coverage_counts[dimension].update(str(v) for v in value)
                elif value not in (None, ""):
                    coverage_counts[dimension][str(value)] += 1
        entropies = {
            dimension: self._normalized_entropy(counts)
            for dimension, counts in coverage_counts.items()
        }
        coverage_score = mean(entropies.values()) if entropies else 0.0
        score = (
            self.novelty_weight * novelty_rate
            + self.coverage_weight * coverage_score
        )
        judge_error_rate = (
            sum(bool(item.get("judge_error")) for item in observations)
            / max(1, len(observations))
        )
        token_cost = mean(
            float(item.get("tokens") or 0.0) for item in observations
        ) if observations else 0.0
        locked_detection_rate = (
            sum(bool(item.get("detected")) for item in locked)
            / max(1, len(locked))
        )
        return {
            "score": score,
            "novelty_rate": novelty_rate,
            "coverage_score": coverage_score,
            "coverage_entropy": entropies,
            "categories": {
                dimension: sorted(counts)
                for dimension, counts in coverage_counts.items()
            },
            "reproducible_signatures": reproducible,
            "locked_detection_rate": locked_detection_rate,
            "judge_error_rate": judge_error_rate,
            "tokens_per_observation": token_cost,
        }

    @staticmethod
    def _normalized_entropy(counts: Counter[str]) -> float:
        total = sum(counts.values())
        if total <= 0:
            return 0.0
        if len(counts) == 1:
            return 1.0
        entropy = -sum(
            (count / total) * math.log(count / total)
            for count in counts.values()
            if count > 0
        )
        return entropy / math.log(len(counts))

    def _paired_confidence_interval(self, pairs: list[Pair]) -> list[float]:
        if not pairs:
            return [0.0, 0.0]
        rng = random.Random(0)
        deltas: list[float] = []
        size = len(pairs)
        for _ in range(self.bootstrap_samples):
            sample = [pairs[rng.randrange(size)] for _ in range(size)]
            champion = self._metrics([pair[0] for pair in sample])
            challenger = self._metrics([pair[1] for pair in sample])
            deltas.append(challenger["score"] - champion["score"])
        deltas.sort()
        lower_index = max(0, int(0.025 * (len(deltas) - 1)))
        upper_index = min(
            len(deltas) - 1, int(0.975 * (len(deltas) - 1))
        )
        return [deltas[lower_index], deltas[upper_index]]

    def _gate_failures(
        self,
        champion: dict[str, Any],
        challenger: dict[str, Any],
        *,
        enabled_taxonomy: dict[str, set[str]] | None,
        challenger_taxonomy: dict[str, set[str]] | None,
    ) -> list[str]:
        failures: list[str] = []
        detection_drop = (
            champion["locked_detection_rate"]
            - challenger["locked_detection_rate"]
        ) * 100
        if detection_drop > self.max_detection_drop_points:
            failures.append(
                f"Locked-pack detection dropped {detection_drop:.2f} points"
            )
        judge_increase = (
            challenger["judge_error_rate"] - champion["judge_error_rate"]
        ) * 100
        if judge_increase > self.max_judge_error_increase_points:
            failures.append(
                f"Judge error rate increased {judge_increase:.2f} points"
            )
        champion_tokens = float(champion["tokens_per_observation"])
        challenger_tokens = float(challenger["tokens_per_observation"])
        if champion_tokens > 0:
            cost_increase = challenger_tokens / champion_tokens - 1.0
            if cost_increase > self.max_token_cost_increase_ratio:
                failures.append(
                    f"Token cost increased {cost_increase * 100:.2f}%"
                )

        required_taxonomy = enabled_taxonomy or {
            dimension: set(values)
            for dimension, values in champion["categories"].items()
        }
        for dimension, required in required_taxonomy.items():
            available = (
                set((challenger_taxonomy or {}).get(dimension, set()))
                if challenger_taxonomy is not None
                else set(challenger["categories"].get(dimension, []))
            )
            missing = set(required) - available
            if missing:
                failures.append(
                    f"Enabled taxonomy coverage lost for {dimension}: "
                    + ", ".join(sorted(missing))
                )
        return failures


class TournamentRunner:
    def __init__(
        self,
        *,
        execute: Callable[
            [str, LearningBundle, int, str, str | None], dict[str, Any]
        ],
        initial_pairs: int = 20,
        batch_pairs: int = 20,
        max_pairs: int = 100,
        bootstrap_samples: int = 1000,
        verifier: PromotionVerifier | None = None,
    ) -> None:
        self.execute = execute
        self.initial_pairs = initial_pairs
        self.batch_pairs = batch_pairs
        self.max_pairs = max_pairs
        self.verifier = verifier or PromotionVerifier(
            bootstrap_samples=bootstrap_samples
        )

    def run(
        self,
        *,
        champion: LearningBundle,
        challenger: LearningBundle,
        target_fingerprint: str,
        validation_contracts: tuple[str, ...],
        enabled_taxonomy: dict[str, set[str]] | None = None,
        challenger_taxonomy: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        if not validation_contracts:
            return {
                "verdict": "failed",
                "reason": "At least one locked validation contract is required.",
                "pairs": 0,
                "observations": [],
            }
        pairs: list[Pair] = []
        next_boundary = self.initial_pairs
        while len(pairs) < self.max_pairs:
            batch_end = min(next_boundary, self.max_pairs)
            while len(pairs) < batch_end:
                pair_index = len(pairs)
                offset = pair_index % self.batch_pairs
                pack = (
                    "locked"
                    if offset < max(1, self.batch_pairs // 2)
                    else "fresh"
                )
                contract = (
                    validation_contracts[
                        pair_index % len(validation_contracts)
                    ]
                    if pack == "locked"
                    else None
                )
                champion_result = self.execute(
                    "champion", champion, pair_index, pack, contract
                )
                challenger_result = self.execute(
                    "challenger", challenger, pair_index, pack, contract
                )
                pairs.append((champion_result, challenger_result))
                if any(
                    str(item.get("target_fingerprint"))
                    != target_fingerprint
                    for item in (champion_result, challenger_result)
                ):
                    return {
                        "verdict": "failed",
                        "reason": "Target fingerprint changed during tournament.",
                        "pairs": len(pairs),
                        "observations": self._flatten(pairs),
                    }

            evidence = self.verifier.evaluate(
                pairs,
                enabled_taxonomy=enabled_taxonomy,
                challenger_taxonomy=challenger_taxonomy,
            )
            if evidence["verdict"] in {"passed", "failed"}:
                return {
                    **evidence,
                    "pairs": len(pairs),
                    "observations": self._flatten(pairs),
                    "target_fingerprint": target_fingerprint,
                }
            if len(pairs) >= self.max_pairs:
                break
            next_boundary = min(
                self.max_pairs, len(pairs) + self.batch_pairs
            )
        return {
            **evidence,
            "verdict": "failed",
            "reason": (
                f"Tournament remained inconclusive at the maximum "
                f"{self.max_pairs} paired observations."
            ),
            "pairs": len(pairs),
            "observations": self._flatten(pairs),
            "target_fingerprint": target_fingerprint,
        }

    @staticmethod
    def _flatten(pairs: Iterable[Pair]) -> list[dict[str, Any]]:
        return [item for pair in pairs for item in pair]


def render_evidence_report(
    result: dict[str, Any],
    *,
    champion_id: str,
    challenger_id: str,
) -> str:
    confidence = result.get("confidence_interval") or [0.0, 0.0]
    failures = result.get("gate_failures") or []
    lines = [
        "# Learning Tournament Evidence",
        "",
        f"- Champion: `{champion_id}`",
        f"- Challenger: `{challenger_id}`",
        f"- Verdict: **{str(result.get('verdict', 'unknown')).upper()}**",
        f"- Paired observations: {int(result.get('pairs') or 0)}",
        f"- Score delta: {float(result.get('score_delta') or 0.0):.6f}",
        (
            "- 95% paired confidence interval: "
            f"[{float(confidence[0]):.6f}, {float(confidence[1]):.6f}]"
        ),
        "",
        "## Gate failures",
        "",
    ]
    lines.extend(
        [f"- {item}" for item in failures]
        or ["- None"]
    )
    lines.extend(
        [
            "",
            "## Decision rationale",
            "",
            str(result.get("reason") or "No rationale recorded."),
            "",
        ]
    )
    return "\n".join(lines)
