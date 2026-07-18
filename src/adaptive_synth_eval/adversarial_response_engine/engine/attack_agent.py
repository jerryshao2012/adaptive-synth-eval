import random
from typing import Optional, List

from .components import AdaptationPlanner, TurnGenerator
from .selector import select_angle
from ..core.models import SessionState, AttackMemory, TurnProbe

# Cross-session framing diversity: each conversation gets a soft "lead register" +
# "probe architecture" bias drawn from its seeded rng, so the ~5000 conversations
# don't collapse onto one voice. These mirror the generator's VARIATION MATRIX; they
# are a soft directive, not a constraint.
_LEAD_REGISTERS = ("formal", "casual", "technical", "emotional")
_PROBE_ARCHITECTURES = ("direct", "lead_with_benign", "sandwich", "multi_step")


class AttackAgent:
    """
    Encapsulates the attack side of the evaluation loop.

    The evaluator owns the target, the judge, the budget, and the session loop.
    The AttackAgent owns everything about *how* to probe: angle selection (a bandit),
    strategy planning, message generation, cross-session attack memory, and persona
    rotation.

    Adaptation model:
      - The bandit (`select_angle`) picks ONE angle per conversation, committed for the
        whole session so the planner can ESCALATE it across turns. The angle is only
        rotated mid-session if the line of attack stalls (consecutive refusals).
      - Cross-session VARIABILITY comes from the bandit spreading angles over many
        conversations plus a per-conversation framing seed.

    Interface contract:
      next_turn(session) -> TurnProbe | None   # None ends the session
      record_session(session) -> None          # call after each session ends
    """

    def __init__(
            self,
            planner: AdaptationPlanner,
            generator: TurnGenerator,
            attack_memory: Optional[AttackMemory] = None,
            persona_pool: Optional[List[str]] = None,
            rng: Optional[random.Random] = None,
            rotate_after_refusals: int = 2,
    ):
        self.planner = planner
        self.generator = generator
        self.attack_memory = attack_memory
        self.persona_pool = persona_pool or []
        self.rng = rng or random.Random()
        self.rotate_after_refusals = rotate_after_refusals
        self._session_count = 0
        self.persona_override: str | None = None  # set externally by evaluator from controller
        self.style_hint: str = ""  # e.g. "aggressive" mode directive
        # Per-conversation state (reset in record_session):
        self._session_angle: str | None = None
        self._variation_seed: str = self._draw_variation_seed()

    @property
    def current_persona(self) -> str:
        if not self.persona_pool:
            return ""
        return self.persona_pool[self._session_count % len(self.persona_pool)]

    def _draw_variation_seed(self) -> str:
        register = self.rng.choice(_LEAD_REGISTERS)
        architecture = self.rng.choice(_PROBE_ARCHITECTURES)
        return f"Lead register: {register}. Preferred probe architecture: {architecture}."

    def _select_session_angle(self, session: SessionState) -> str:
        """Commit one angle per conversation; rotate only when the attack stalls.

        Returns the committed angle, drawing a new one when none is set yet or when
        consecutive refusals indicate the current line of attack is exhausted.
        """
        stalled = (
                self.rotate_after_refusals > 0
                and session.repeated_refusals >= self.rotate_after_refusals
        )
        if self._session_angle is None or stalled:
            exclude = {self._session_angle} if (stalled and self._session_angle) else None
            self._session_angle = select_angle(self.attack_memory, self.rng, exclude=exclude)
        return self._session_angle

    def next_turn(self, session: SessionState) -> Optional[TurnProbe]:
        """Returns None when the session should end (planner says stop, or generator yields empty input)."""
        persona = self.persona_override or self.current_persona
        angle = self._select_session_angle(session)
        plan = self.planner.plan(
            session, self.attack_memory,
            target_persona=persona,
            style_hint=self.style_hint,
            fixed_angle=angle,
        )
        if plan.stop_session:
            return None

        # The bandit owns the angle — pin it onto the plan so memory/angle_stats stay
        # consistent regardless of what the planner echoed. (sub_tactic stays the LLM's.)
        plan.attack_angle = angle
        plan.raw["attack_angle"] = angle

        generated = self.generator.generate(
            session=session,
            strategy_instruction=plan.next_generator_instruction,
            variation_seed=self._variation_seed,
        )
        if not generated.user_input:
            return None

        return TurnProbe(
            user_input=generated.user_input,
            plan=plan,
            generated=generated,
        )

    def record_session(self, session: SessionState) -> None:
        if self.attack_memory is not None:
            self.attack_memory.record_session(session)
        self._session_count += 1
        # Reset per-conversation state so the next session commits a fresh angle and
        # framing seed.
        self._session_angle = None
        self._variation_seed = self._draw_variation_seed()
