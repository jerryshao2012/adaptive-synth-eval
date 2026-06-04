"""Realtime console display with distinct styling for synth vs adversarial turns.

Adversarial turns get a red border + 🎯 icon + scenario_type tag in the title,
so it's obvious at a glance which turn type is firing. Synth turns keep ASE's
blue 🧑 styling.
"""
from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


def _console() -> Console:
    return Console(file=sys.stdout)


def display_user_turn(
    *,
    conversation_id: str,
    persona_id: str,
    scenario_id: str,
    turn_id: int,
    user_message: str,
    mode: str,                       # "synth" | "adversarial"
    adv_scenario_type: str = "",
) -> None:
    console = _console()
    if mode == "adversarial":
        tag = adv_scenario_type or "adversarial"
        title = f"🎯 {persona_id} [ADVERSARIAL · {tag}]"
        border = "red"
    else:
        title = f"🧑 {persona_id} [SYNTH]"
        border = "blue"

    console.rule(
        f"Conversation {conversation_id} | Scenario {scenario_id} | Turn {turn_id} | Mode: {mode.upper()}"
    )
    console.print(Panel(user_message, title=title, border_style=border))


def display_bot_turn(*, bot_message: str) -> None:
    console = _console()
    console.print(Panel(bot_message, title="🤖 Assistant", border_style="green"))


def display_judge_verdict(*, verdict) -> None:
    """Show the adversarial judge's reasoning + short_reason after each adversarial turn."""
    console = _console()
    held = "guardrail held" if verdict.guardrail_worked else "GUARDRAIL FAILED"
    near = " · near-miss" if verdict.near_miss else ""
    title = (
        f"⚖️  Judge · failure_score={verdict.failure_score} · "
        f"{verdict.failure_type} · {held}{near}"
    )
    # Wrap in Text so bracketed placeholders in the reasoning (e.g. "[policy pressure]")
    # are printed literally rather than parsed as rich markup.
    body = Text()
    if verdict.short_reason:
        body.append(verdict.short_reason + "\n\n", style="bold")
    body.append(verdict.reasoning or "(no reasoning provided)")
    border = "yellow" if verdict.guardrail_worked else "red"
    console.print(Panel(body, title=title, border_style=border))
