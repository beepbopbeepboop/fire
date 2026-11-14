# Regression pin for FORMAL_arm64_step_cannot_step_nine_wired_encodings.
# The two WRONG arms (CMN writes no Rd; imm12 ignores sh) and the
# twelve NOSTEP memory forms were fixed in lib/ProofLib.lean (commit
# 0ad2ef33 / merged 2026-10-13). The pinning verification is the
# existing TestUnsignedOffsetAccess::test_the_model_agrees_with_the_cpu
# in test_formal_call_proof_gen.py, which compares arm64_step against
# the CPU for all of them (CMN, TST, adds, sub, add imm12, reg-offset,
# narrow/unscaled, ldur/stur, blr not included because it needs
# arm64_step_call machinery).
# This file exists only to name the bug doc that it replaces.
