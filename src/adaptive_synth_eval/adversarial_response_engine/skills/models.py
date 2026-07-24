from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AttackSkill:
    """Validated, immutable view of one curated attack-method package."""

    name: str
    description: str
    compatibility: str
    instructions: str
    directory: Path
    angle: str
    version: str
    sub_tactics: tuple[str, ...]
    accumulation: bool
    scenario_types: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    package_digest: str
    note: str = ""

    def supports_scenario(self, scenario_type: str) -> bool:
        return "*" in self.scenario_types or scenario_type in self.scenario_types
