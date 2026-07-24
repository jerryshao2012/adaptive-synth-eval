from __future__ import annotations

import math
import random
from collections.abc import Sequence

from ..core.models import AttackMemory
from .models import AttackSkill


def select_skill(
    candidates: Sequence[AttackSkill],
    memory: AttackMemory | None,
    rng: random.Random,
    *,
    c: float = 1.4,
) -> AttackSkill:
    """Select a compatible skill with UCB1 and seeded tie-breaking."""
    if not candidates:
        raise ValueError("at least one compatible attack skill is required")
    choices = list(candidates)
    rng.shuffle(choices)
    stats = memory.skill_stats() if memory else {}
    total_pulls = sum(stat.n for stat in stats.values()) + 1

    def score(skill: AttackSkill) -> float:
        stat = stats.get(f"{skill.name}@{skill.version}")
        if stat is None or stat.n == 0:
            return float("inf")
        reward = stat.mean_score / 4.0
        near_bonus = 0.5 if stat.any_near_miss else 0.0
        explore = c * math.sqrt(math.log(total_pulls) / stat.n)
        return reward + near_bonus + explore

    return max(choices, key=score)
