# engine/taxonomy.py
#
# Single source of truth for the attack strategy taxonomy. The editable data
# lives in the sibling `attack_taxonomy.yaml`; this module loads + validates it
# once at import and exposes typed access plus the prompt renderers. To add or
# edit an angle / sub-tactic / scenario note, change the YAML, not this file.
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import yaml

_CATALOG_FILE = "attack_taxonomy.yaml"


@dataclass(frozen=True)
class AngleSpec:
    name: str
    description: str
    sub_tactics: tuple[str, ...]
    note: str = ""
    accumulation: bool = False


def _load_catalog() -> tuple[dict[str, AngleSpec], dict[str, str]]:
    raw = yaml.safe_load(resources.files(__package__).joinpath(_CATALOG_FILE).read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{_CATALOG_FILE}: top-level YAML must be a mapping")

    angles_raw = raw.get("angles")
    if not isinstance(angles_raw, dict) or not angles_raw:
        raise ValueError(f"{_CATALOG_FILE}: 'angles' must be a non-empty mapping")

    angles: dict[str, AngleSpec] = {}
    for name, body in angles_raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"{_CATALOG_FILE}: angle '{name}' must be a mapping")
        subs = body.get("sub_tactics")
        if not isinstance(subs, list) or not subs:
            raise ValueError(f"{_CATALOG_FILE}: angle '{name}' needs a non-empty 'sub_tactics' list")
        angles[name] = AngleSpec(
            name=name,
            description=str(body.get("description", "")).strip(),
            sub_tactics=tuple(str(s) for s in subs),
            note=str(body.get("note", "")).strip(),
            accumulation=bool(body.get("accumulation", False)),
        )

    notes_raw = raw.get("scenario_strategy_notes", {}) or {}
    if not isinstance(notes_raw, dict):
        raise ValueError(f"{_CATALOG_FILE}: 'scenario_strategy_notes' must be a mapping")
    scenario_notes = {str(k): str(v).strip() for k, v in notes_raw.items()}

    return angles, scenario_notes


ANGLES: dict[str, AngleSpec]
SCENARIO_STRATEGY_NOTES: dict[str, str]
ANGLES, SCENARIO_STRATEGY_NOTES = _load_catalog()

ANGLE_NAMES: list[str] = list(ANGLES.keys())
ACCUMULATION_ANGLES: set[str] = {name for name, spec in ANGLES.items() if spec.accumulation}


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
    lines = [f"{spec.name} — {spec.description}", f"  sub-tactics: {' | '.join(spec.sub_tactics)}"]
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
