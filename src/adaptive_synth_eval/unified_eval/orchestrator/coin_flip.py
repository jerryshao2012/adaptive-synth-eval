"""Per-turn synth/adversarial selection.

Three scheduler modes (see unified_eval.config.schemas.Schedule):
  - bernoulli: independent coin flip per turn
  - phased:    first `warmup_turns` are synth, the rest are adversarial
  - min_each:  guarantee floors, fill the rest by Bernoulli at p_synth
"""
from __future__ import annotations

import hashlib
import random

from adaptive_synth_eval.unified_eval.config.schemas import Schedule


def plan_turn_modes(schedule: Schedule, turn_count: int, rng: random.Random) -> list[str]:
    """Return the ordered list of turn modes for a single conversation.

    Each element is "synth" or "adversarial". Length == turn_count.
    """
    mode = schedule.mode
    if mode == "bernoulli":
        return [
            "synth" if rng.random() < schedule.p_synth else "adversarial"
            for _ in range(turn_count)
        ]

    if mode == "phased":
        warmup = max(0, min(schedule.warmup_turns, turn_count))
        return ["synth"] * warmup + ["adversarial"] * (turn_count - warmup)

    if mode == "ramp":
        # Gradual hand-off: `warmup_turns` pure synth, then P(adversarial) climbs
        # linearly from ~0 to ~1 across the remaining turns — early turns stay mostly
        # legit (refreshing grounding), pressure builds toward the end. Deterministic
        # given the seeded rng.
        warmup = max(0, min(schedule.warmup_turns, turn_count))
        modes = ["synth"] * warmup
        remaining = turn_count - warmup
        for i in range(remaining):
            p_adversarial = (i + 1) / (remaining + 1)
            modes.append("adversarial" if rng.random() < p_adversarial else "synth")
        return modes

    if mode == "min_each":
        min_s = max(0, schedule.min_synth)
        min_a = max(0, schedule.min_adversarial)
        if min_s + min_a > turn_count:
            # Floors don't fit; distribute proportionally.
            ratio = turn_count / (min_s + min_a)
            min_s = int(min_s * ratio)
            min_a = turn_count - min_s
        modes: list[str] = ["synth"] * min_s + ["adversarial"] * min_a
        fill = turn_count - len(modes)
        modes += [
            "synth" if rng.random() < schedule.p_synth else "adversarial"
            for _ in range(fill)
        ]
        rng.shuffle(modes)
        return modes

    raise ValueError(f"Unknown schedule.mode: {mode!r}")


def make_conversation_rng(run_seed: int | None, conversation_id: str) -> random.Random:
    """Stable RNG keyed by (run seed, conversation_id) for reproducible runs."""
    seed_material = f"{run_seed if run_seed is not None else 0}:{conversation_id}".encode("utf-8")
    digest = hashlib.sha256(seed_material).digest()
    seed = int.from_bytes(digest[:8], "big") & 0xFFFFFFFF
    return random.Random(seed)


# --- Backwards-compatible helpers (still used by older tests) ----------------

def pick_turn_mode(rng: random.Random, p_synth: float) -> str:
    """Single Bernoulli draw. Kept for backwards compatibility."""
    p = max(0.0, min(1.0, float(p_synth)))
    return "synth" if rng.random() < p else "adversarial"
