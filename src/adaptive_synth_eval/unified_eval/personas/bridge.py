"""Adversarial-side helpers.

The adversarial side (ARE) uses its own neutral red-team register; the synth
persona's voice is intentionally NOT injected here. The synth persona shapes
the synth turns (via ASE's UserSimulator); the attacker plans and writes its
own probes.

What stays in this module: the per-scenario_type default for `target_persona`
used by the `persona-hijack` scenario type — i.e. *what persona the attacker
tries to make the BOT adopt* (a doctor, a lawyer). This is distinct from any
notion of persona voice on the attacker side.
"""
from __future__ import annotations

# Default hijack targets per ARE scenario_type. Used when the contract omits
# adversarial_scenario_catalog[].hijack_target.
HIJACK_TARGET_DEFAULTS: dict[str, str] = {
    "persona-hijack": "a licensed professional giving authoritative advice within their regulated domain",
    "toxicity": "",
    "prompt-injection": "",
    "data-leakage": "",
    "hallucination": "",
    "tool-call": "",
    "document-exfiltration": "",
    "system-prompt-override": "",
    "malicious-resource-fetching": "",
    "data-pii-leak": "",
    "unsupervised-contracts": "",
}


def resolve_hijack_target(scenario_type: str, override: str | None) -> str:
    """Pick the hijack target string. Override wins; otherwise default per scenario_type."""
    if override:
        return override
    return HIJACK_TARGET_DEFAULTS.get(scenario_type, "")
