from __future__ import annotations

from adaptive_synth_eval.unified_eval.orchestrator.coin_flip import make_conversation_rng


def test_make_conversation_rng_is_stable_for_same_inputs():
    seq1 = [make_conversation_rng(42, "conv-123").random() for _ in range(3)]
    seq2 = [make_conversation_rng(42, "conv-123").random() for _ in range(3)]
    assert seq1 == seq2


def test_make_conversation_rng_changes_when_inputs_change():
    a = make_conversation_rng(42, "conv-123").random()
    b = make_conversation_rng(43, "conv-123").random()
    c = make_conversation_rng(42, "conv-124").random()
    assert a != b
    assert a != c
