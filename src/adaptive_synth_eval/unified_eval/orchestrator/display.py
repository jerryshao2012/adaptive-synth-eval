"""Realtime console display with distinct styling for synth vs adversarial turns.

Adversarial turns get a red border + 🎯 icon + scenario_type tag in the title,
so it's obvious at a glance which turn type is firing. Synth turns keep ASE's
blue 🧑 styling.
"""
from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel


def _console() -> Console:
    return Console(file=sys.stdout)


def display_user_turn(
        *,
        conversation_id: str,
        persona_id: str,
        scenario_id: str,
        turn_id: int,
        user_message: str,
        mode: str,  # "synth" | "adversarial"
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


def display_judge_turn(
        *,
        failure_score: int,
        failure_type: str,
        refusal_quality: int,
        near_miss: bool,
        short_reason: str,
        threshold: int,
) -> None:
    """Render the adversarial SafetyJudge verdict inline, right under the bot reply.

    Color-coded by severity so a failure is obvious at a glance:
      red    — failure_score >= threshold (a finding)
      yellow — partial leak / near-miss (0 < score < threshold)
      green  — guardrail held (score 0)
    """
    console = _console()
    if failure_score >= threshold:
        border, verdict = "red", f"FAIL {failure_score}/{threshold}"
    elif near_miss or failure_score > 0:
        border, verdict = "yellow", f"NEAR-MISS {failure_score}/{threshold}"
    else:
        border, verdict = "green", f"SAFE {failure_score}/{threshold}"

    title = f"⚖️  JUDGE [{verdict} · {failure_type}]"
    body = f"refusal_quality={refusal_quality}  near_miss={near_miss}"
    if short_reason:
        body += f"\n{short_reason.strip()}"
    console.print(Panel(body, title=title, border_style=border))
