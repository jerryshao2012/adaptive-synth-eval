# engine/selector.py  (new)
import math

from .taxonomy import Angle, ANGLE_SUBTACTICS


def _tried_pairs(session) -> set[tuple[str, str]]:
    return {
        (t.strategy_before_turn.get("attack_angle"),
         t.strategy_before_turn.get("sub_tactic"))
        for t in session.turns
    }


def select_pair(session, memory, rng, c: float = 1.4):
    """
    UCB1 over angles (reward = normalized failure_score, + near-miss bonus),
    then a uniform pick among that angle's still-untried sub-tactics.
    Returns (angle, sub_tactic) or None when the pair-space is exhausted.
    """
    tried = _tried_pairs(session)
    open_angles = [
        a for a in Angle
        if any((a.value, s) not in tried for s in ANGLE_SUBTACTICS[a])
    ]
    if not open_angles:
        return None

    stats = memory.angle_stats() if memory else {}  # see 1.2
    total_pulls = sum(s.n for s in stats.values()) + 1

    def ucb(a: Angle) -> float:
        st = stats.get(a.value)
        if not st or st.n == 0:
            return float("inf")  # try each angle once
        reward = st.mean_score / 4.0  # normalize 0..4 -> 0..1
        near_bonus = 0.5 if st.any_near_miss else 0.0
        explore = c * math.sqrt(math.log(total_pulls) / st.n)
        return reward + near_bonus + explore

    angle = max(open_angles, key=ucb)
    untried = [s for s in ANGLE_SUBTACTICS[angle] if (angle.value, s) not in tried]
    return angle.value, rng.choice(untried)
