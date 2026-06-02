from typing import Optional, List

from .components import AdaptationPlanner, TurnGenerator
from ..core.models import SessionState, AttackMemory, TurnProbe


class AttackAgent:
    """
    Encapsulates the attack side of the evaluation loop.

    The evaluator owns the target, the judge, the budget, and the session loop.
    The AttackAgent owns everything about *how* to probe: strategy planning,
    message generation, cross-session attack memory, and persona rotation.

    Interface contract:
      next_turn(session) -> {"user_input": str, "strategy": dict, "done": bool}
      record_session(session) -> None   # call after each session ends
    """

    def __init__(
            self,
            planner: AdaptationPlanner,
            generator: TurnGenerator,
            attack_memory: Optional[AttackMemory] = None,
            persona_pool: Optional[List[str]] = None,
    ):
        self.planner = planner
        self.generator = generator
        self.attack_memory = attack_memory
        self.persona_pool = persona_pool or []
        self._session_count = 0
        self.persona_override: str | None = None  # set externally by evaluator from controller
        self.style_hint: str = ""  # e.g. "aggressive" mode directive

    @property
    def current_persona(self) -> str:
        if not self.persona_pool:
            return ""
        return self.persona_pool[self._session_count % len(self.persona_pool)]

    def next_turn(self, session: SessionState) -> Optional[TurnProbe]:
        """Returns None when the session should end (planner says stop, or generator yields empty input)."""
        persona = self.persona_override or self.current_persona
        plan = self.planner.plan(
            session, self.attack_memory,
            target_persona=persona,
            style_hint=self.style_hint,
        )
        if plan.stop_session:
            return None

        generated = self.generator.generate(
            session=session,
            strategy_instruction=plan.next_generator_instruction,
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
