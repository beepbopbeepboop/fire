"""Regression/pinning test for AXIOM_CLOSURE — fails if the closure table rots."""
from test_formal_admitted import AXIOM_CLOSURE


def test_axiom_closure_is_pinned_not_stale():
    # Measured 2026-10-05; re-measured 2026-11-06 (sharded library, restored content, step 02).
    # If any module's counts drift, this fails — the table must be
    # re-measured, not widened.
    assert AXIOM_CLOSURE["Contracts"] == (7, 0, 7, 0, 0, 0)
    assert AXIOM_CLOSURE["IEEE754"] == (26, 19, 7, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLib"] == (272, 17, 249, 0, 6, 0)
    assert AXIOM_CLOSURE["Refine"] == (29, 0, 29, 0, 0, 0)
    assert AXIOM_CLOSURE["X86"] == (175, 2, 172, 0, 1, 0)
    assert AXIOM_CLOSURE["work"] == (20, 0, 18, 0, 2, 0)
    assert AXIOM_CLOSURE["Specs"] == (67, 0, 67, 0, 0, 0)
    assert AXIOM_CLOSURE["Peephole"] == (29, 4, 22, 0, 3, 0)
    assert AXIOM_CLOSURE["Scaffold"] == (12, 0, 12, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps1"] == (22, 20, 2, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps2"] == (9, 9, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps3"] == (4, 4, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps4"] == (5, 5, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps5"] == (4, 4, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps6"] == (4, 4, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps7"] == (6, 6, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps8"] == (5, 5, 0, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLibSteps"] == (0, 0, 0, 0, 0, 0)
    # Partition check: asked == reaches + clean + text_only + closure_only
    for mod, (asked, reaches, clean, text_only, closure_only, ofrb) in AXIOM_CLOSURE.items():
        assert asked == reaches + clean + text_only + closure_only, \
            f"{mod}: {asked} != {reaches}+{clean}+{text_only}+{closure_only}"
    assert ofrb == 0, "ofReduceBool must be zero everywhere"
