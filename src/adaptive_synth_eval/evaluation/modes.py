from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Load loaders and runners lazily to prevent circular imports or premature loading
from adaptive_synth_eval.config.contract import load_contract as load_synth_contract
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation as run_synth_simulation
from adaptive_synth_eval.unified_eval.config.contract import load_unified_contract
from adaptive_synth_eval.unified_eval.orchestrator.runner import run_unified


@dataclass(frozen=True)
class EvaluationMode:
    name: str
    load_contract: Callable[[str | Path], Any]
    run: Callable[..., dict[str, Any]]


EVALUATION_MODES = {
    "synth": EvaluationMode(
        name="synth",
        load_contract=load_synth_contract,
        run=run_synth_simulation,
    ),
    "unified": EvaluationMode(
        name="unified",
        load_contract=load_unified_contract,
        run=run_unified,
    ),
}


def get_mode(name: str) -> EvaluationMode:
    if name not in EVALUATION_MODES:
        raise ValueError(f"Unknown evaluation mode: {name}. Supported: {list(EVALUATION_MODES.keys())}")
    return EVALUATION_MODES[name]
