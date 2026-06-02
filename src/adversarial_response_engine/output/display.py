"""
Shared rich display utilities for adversarial eval and interactive chat.

Both the automated on_turn callback and the --chat REPL use these functions
so the visual output is identical regardless of who drives the conversation.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

try:
    from rich.console import Console
    from rich.panel import Panel

    _RICH_AVAILABLE = True
except ImportError:
    Console = None  # type: ignore[misc,assignment]
    Panel = None  # type: ignore[assignment]
    _RICH_AVAILABLE = False

if TYPE_CHECKING:
    from ..core.models import TurnRecord


def make_console() -> "Console":
    """Fresh Console bound to current stdout (prompt_toolkit-safe)."""
    if not _RICH_AVAILABLE:
        raise RuntimeError("rich is not installed")
    return Console(file=sys.stdout)


def show_rule(console: "Console", text: str) -> None:
    console.rule(text)


def show_message(console: "Console", text: str, *, title: str, color: str) -> None:
    console.print(Panel(text or "(empty)", title=title, border_style=color))


def show_user(console: "Console", text: str, title: str = "🧑 You") -> None:
    show_message(console, text, title=title, color="blue")


def show_bot(console: "Console", text: str, title: str = "🤖 Target Bot") -> None:
    show_message(console, text, title=title, color="green")


def show_judge(console: "Console", judge_result: dict, error: str = "") -> None:
    score = judge_result.get("failure_score", "?")
    harm = judge_result.get("harm_potential", "?")
    rq = judge_result.get("refusal_quality", "?")
    near_miss = judge_result.get("near_miss", False)
    color = "green" if score == 0 else ("yellow" if isinstance(score, int) and score <= 2 else "red")
    text = f"score={score}  harm={harm}  refusal_quality={rq}  near_miss={near_miss}"
    if error:
        text += f"\n⚠ {error}"
    show_message(console, text, title="⚖ Judge", color=color)


def show_turn(console: "Console", turn_record: "TurnRecord", session_id: str, turn_num: int) -> None:
    """Render a full attacker→bot→judge turn block."""
    jr = turn_record.judge_result or {}
    strategy = turn_record.strategy_before_turn or {}
    angle = strategy.get("attack_angle", "—")
    sub = strategy.get("sub_tactic", "—")
    score = jr.get("failure_score", "?")
    color = "green" if score == 0 else ("yellow" if isinstance(score, int) and score <= 2 else "red")

    sid = session_id[-8:] if session_id else "?"
    show_rule(
        console,
        f"[bold]Session {sid}[/bold]  Turn {turn_num}  "
        f"[dim]{angle} / {sub}[/dim]  "
        f"[{color}]score={score}[/{color}]",
    )
    show_user(console, turn_record.user_input or "", title="🧑 Attacker")
    show_bot(console, turn_record.chatbot_response or "")
    show_judge(console, jr, error=turn_record.error or "")
