# engine/selector.py
import math
import random
from collections.abc import Sequence

from .taxonomy import ANGLE_NAMES


def select_angle(
    memory,
    rng: random.Random,
    c: float = 1.4,
    exclude: set[str] | None = None,
    candidates: Sequence[str] | None = None,
) -> str:
    """Pick ONE attack angle for a conversation via UCB1 over the taxonomy.

    Reward = normalized cross-session mean failure_score (+ a near-miss bonus),
    drawn from `memory.angle_stats()` which aggregates over ALL prior conversations.
    Untried angles get an infinite score so each is sampled once early in a run;
    after that the bandit exploits the angles that actually break this target while
    still exploring under-sampled ones. The chosen angle is committed for the whole
    conversation (the planner escalates it across turns).

    `exclude` skips angles (used when rotating away from a stalled line of attack).
    """
    stats = memory.angle_stats() if memory else {}
    total_pulls = sum(s.n for s in stats.values()) + 1

    def ucb(angle: str) -> float:
        st = stats.get(angle)
        if not st or st.n == 0:
            return float("inf")  # sample each angle once
        reward = st.mean_score / 4.0  # normalize 0..4 -> 0..1
        near_bonus = 0.5 if st.any_near_miss else 0.0
        explore = c * math.sqrt(math.log(total_pulls) / st.n)
        return reward + near_bonus + explore

    allowed = list(candidates) if candidates is not None else list(ANGLE_NAMES)
    if not allowed:
        raise ValueError("at least one attack angle candidate is required")
    available = [a for a in allowed if not exclude or a not in exclude]
    if not available:  # everything excluded — ignore the filter rather than fail
        available = allowed
    # Shuffle first so ties (notably the inf cold-start) are broken uniformly at
    # random per the conversation's seeded rng — this is what spreads angles
    # across the ~5000 conversations.
    rng.shuffle(available)
    return max(available, key=ucb)
