#!/usr/bin/env python3
"""
Demonstration of the enhanced realtime prompt with persona ID display.

This script shows how the current persona ID is visible in the interactive
realtime controls prompt during multi-persona mode, providing continuous
visibility when persona switching is available.
"""

from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController


def demo_prompt_with_persona():
    """Demonstrate the dynamic prompt text with persona ID."""

    print("=" * 80)
    print("Realtime Prompt Enhancement Demo")
    print("=" * 80)
    print()

    # Setup personas
    personas = {
        "P001": {"role": "new_employee", "location": "Canada"},
        "P002": {"role": "manager", "location": "USA"},
        "P003": {"role": "hr_specialist", "location": "UK"},
    }

    print("\n--- MULTI-PERSONA MODE ---")
    print("(Persona ID shown in prompt for visibility)")
    print()

    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas=personas,
    )

    print("Initial state (no persona set):")
    print(f"  Prompt: '{controller.prompt_text}'")
    print()

    print("After setting active persona to P001:")
    controller.set_active_persona("P001")
    print(f"  Prompt: '{controller.prompt_text}'")
    print()

    print("After switching to P002:")
    controller.set_active_persona("P002")
    print(f"  Prompt: '{controller.prompt_text}'")
    print()

    print("After switching to P003:")
    controller.set_active_persona("P003")
    print(f"  Prompt: '{controller.prompt_text}'")
    print()

    print("\n--- SINGLE-PERSONA MODE ---")
    print("(Persona ID hidden to avoid redundancy)")
    print()

    controller_single = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P001": {"role": "new_employee", "location": "Canada"}},
        single_persona_mode=True,
    )

    print("Single-persona mode with P001 active:")
    controller_single.set_active_persona("P001")
    print(f"  Prompt: '{controller_single.prompt_text}'")
    print("  (Note: Persona ID not shown since switching is disabled)")
    print()

    print("=" * 80)
    print("Benefits:")
    print("  ✓ Multi-persona: Continuous visibility when switching is possible")
    print("  ✓ Single-persona: Clean prompt without redundant information")
    print("  ✓ Immediate feedback: Updates instantly when switching personas")
    print("  ✓ Non-intrusive: Doesn't clutter conversation display")
    print("  ✓ Context-aware: Shows relevant info only where it adds value")
    print("=" * 80)


if __name__ == "__main__":
    demo_prompt_with_persona()
