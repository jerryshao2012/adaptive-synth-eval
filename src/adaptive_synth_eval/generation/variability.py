from __future__ import annotations

import random

from adaptive_synth_eval.config.schemas import FailureInjection


def choose_failure_modes(failure: FailureInjection, rng: random.Random) -> list[str]:
    modes = []
    for name, probability in failure.__dict__.items():
        if float(probability or 0.0) >= 1.0 or rng.random() < float(probability or 0.0):
            modes.append(name)
    return modes


def apply_typos(text: str) -> str:
    words = text.split()
    if not words:
        return text
    words[0] = words[0].replace("a", "a", 1) + "?"
    return " ".join(words)
