"""Compatibility facade over the packaged Agent Skills attack catalog."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import yaml

from ..skills.models import AttackSkill
from ..skills.registry import get_builtin_registry

CATALOG_SOURCE = "agent-skills"
_SCENARIO_GUIDANCE_FILE = "scenario_guidance.yaml"
_LEGACY_ANGLE_ORDER = (
    "angle_shift",
    "indirect_priming",
    "specificity_escalation",
    "authority_injection",
    "deflection_wrap",
    "role_entrapment",
    "social_pressure",
    "memory_exploitation",
    "semantic_drift",
    "decomposition_attack",
    "hypothetical_framing",
)


@dataclass(frozen=True)
class AngleSpec:
    name: str
    description: str
    sub_tactics: tuple[str, ...]
    note: str = ""
    accumulation: bool = False


def _merge_angle_skills(angle: str, skills: list[AttackSkill]) -> AngleSpec:
    descriptions = tuple(dict.fromkeys(skill.description for skill in skills))
    notes = tuple(dict.fromkeys(skill.note for skill in skills if skill.note))
    sub_tactics = tuple(
        dict.fromkeys(
            sub_tactic for skill in skills for sub_tactic in skill.sub_tactics
        )
    )
    return AngleSpec(
        name=angle,
        description=" / ".join(descriptions),
        sub_tactics=sub_tactics,
        note=" ".join(notes),
        accumulation=any(skill.accumulation for skill in skills),
    )


def _load_catalog() -> tuple[dict[str, AngleSpec], dict[str, str]]:
    registry = get_builtin_registry()
    by_angle: dict[str, list[AttackSkill]] = {}
    for skill in registry.skills:
        by_angle.setdefault(skill.angle, []).append(skill)
    ordered_angles = [angle for angle in _LEGACY_ANGLE_ORDER if angle in by_angle]
    ordered_angles.extend(sorted(set(by_angle) - set(ordered_angles)))
    angles = {
        angle: _merge_angle_skills(angle, by_angle[angle]) for angle in ordered_angles
    }

    notes_raw = (
        yaml.safe_load(
            resources.files(__package__)
            .joinpath(_SCENARIO_GUIDANCE_FILE)
            .read_text("utf-8")
        )
        or {}
    )
    if not isinstance(notes_raw, dict):
        raise ValueError(f"{_SCENARIO_GUIDANCE_FILE}: top-level YAML must be a mapping")
    scenario_notes = {str(k): str(v).strip() for k, v in notes_raw.items()}

    return angles, scenario_notes


ANGLES: dict[str, AngleSpec]
SCENARIO_STRATEGY_NOTES: dict[str, str]
ANGLES, SCENARIO_STRATEGY_NOTES = _load_catalog()

ANGLE_NAMES: list[str] = list(ANGLES.keys())
ACCUMULATION_ANGLES: set[str] = {
    name for name, spec in ANGLES.items() if spec.accumulation
}


def is_valid_angle(name: str) -> bool:
    return name in ANGLES


def sub_tactics_for(angle: str) -> tuple[str, ...]:
    spec = ANGLES.get(angle)
    return spec.sub_tactics if spec else ()


def render_angle_detail(angle: str) -> str:
    """Render just the assigned angle's block: description + sub-tactic list + note.

    Injected into the planner prompt so it knows the angle's meaning and which
    sub-tactics are available, without re-listing the whole taxonomy.
    """
    spec = ANGLES.get(angle)
    if spec is None:
        return f"{angle} (unknown angle — no taxonomy entry found)"
    lines = [
        f"{spec.name} — {spec.description}",
        f"  sub-tactics: {' | '.join(spec.sub_tactics)}",
    ]
    if spec.note:
        lines.append(f"  note: {spec.note}")
    return "\n".join(lines)


def scenario_strategy_note(scenario_type: str) -> str:
    """The one strategy note relevant to this scenario (flattened to a single line)."""
    note = SCENARIO_STRATEGY_NOTES.get(scenario_type, "")
    return " ".join(note.split()) if note else ""


def render_taxonomy_for_prompt() -> str:
    """Build the full angle menu (catalog reference / diagnostics)."""
    return "\n\n".join(render_angle_detail(name) for name in ANGLE_NAMES)
