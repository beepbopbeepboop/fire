"""Regression/pinning test for AXIOM_CLOSURE — fails if the closure table rots."""
from test_formal_admitted import AXIOM_CLOSURE


def test_axiom_closure_is_pinned_not_stale():
    # Measured 2026-10-05 / re-derived through 2026-10-18 merges.
    # If any module's counts drift, this fails — the table must be
    # re-measured, not widened.
    assert AXIOM_CLOSURE["Contracts"] == (7, 0, 7, 0, 0, 0)
    assert AXIOM_CLOSURE["IEEE754"] == (26, 19, 7, 0, 0, 0)
    assert AXIOM_CLOSURE["ProofLib"] == (315, 62, 248, 0, 5, 0)
    assert AXIOM_CLOSURE["Refine"] == (29, 0, 29, 0, 0, 0)
    assert AXIOM_CLOSURE["X86"] == (156, 2, 153, 0, 1, 0)
    assert AXIOM_CLOSURE["work"] == (20, 0, 18, 0, 2, 0)
    assert AXIOM_CLOSURE["Specs"] == (66, 0, 66, 0, 0, 0)
    assert AXIOM_CLOSURE["Peephole"] == (14, 1, 10, 0, 3, 0)
    # Partition check: asked == reaches + clean + text_only + closure_only
    for mod, (asked, reaches, clean, text_only, closure_only, ofrb) in AXIOM_CLOSURE.items():
        assert asked == reaches + clean + text_only + closure_only, \
            f"{mod}: {asked} != {reaches}+{clean}+{text_only}+{closure_only}"
    assert ofrb == 0, "ofReduceBool must be zero everywhere"
