#!/usr/bin/env python3
"""Quick regression for signed dec-while model (item 2 / cond_val)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formal.arm64_proof_gen as G

def test_cond_val_has_sign_split():
    block = G._gen_dec_while_block("countdown", "n", "GT")
    # cond_val must mention the sign-bit split (< 2^63)
    assert "9223372036854775808" in block, "cond_val missing signed split"
    # pred_iff must use conjunction (∧) not implication (→)
    assert "∧ 0 < UInt64.ofNat m" in block, "pred_iff GT missing conjunction"
    print("PASS: signed model split present")

if __name__ == "__main__":
    test_cond_val_has_sign_split()
