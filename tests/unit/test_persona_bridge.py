"""Tests for the adversarial-side persona bridge.

After simplification this module only handles `hijack_target` resolution for
the persona-hijack scenario type. The synth persona is NOT injected into the
adversarial attacker's voice.
"""
from __future__ import annotations

from unified_eval.personas.bridge import (
    HIJACK_TARGET_DEFAULTS,
    resolve_hijack_target,
)


def test_resolve_hijack_target_uses_override():
    assert resolve_hijack_target(
        "persona-hijack", "a sworn judge advising the bench"
    ) == "a sworn judge advising the bench"


def test_resolve_hijack_target_falls_back_to_default_for_persona_hijack():
    assert resolve_hijack_target("persona-hijack", None) == HIJACK_TARGET_DEFAULTS["persona-hijack"]


def test_resolve_hijack_target_empty_for_other_scenarios():
    assert resolve_hijack_target("toxicity", None) == ""
    assert resolve_hijack_target("prompt-injection", None) == ""
    assert resolve_hijack_target("data-pii-leak", None) == ""
