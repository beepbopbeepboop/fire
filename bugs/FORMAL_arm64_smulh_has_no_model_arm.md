# FORMAL_arm64_smulh_has_no_model_arm: the high half of a multiply is emitted and modelled nowhere

**Found 2026-10-05 by `tools/formal_isa_census.py`**, the instruction-coverage
census this tree did not have: `encode_smulh_xd_xn_xm` is called by
`formal/arm64_codegen.py`, has a byte-exact `as` differential, and is drawn by
`tools/formal_model_fuzz.py`'s `flagged` mix — and `lib/ProofLib.lean`'s
`arm64_step` has no branch that matches its word, so every case that draws it
is a `NOSTEP`. A refusal is the worst failure the harness has: a proof that
cannot step an instruction is a proof about nothing.

## What I ran

```
$ python3 tools/formal_isa_census.py --arch arm64 | grep -A1 smulh
   encode_smulh_xd_xn_xm           NO   yes  yes  0 ex:   arm64_codegen.py x1
                                       no arm64_step branch matches
```

The word is `0x9b407c00 | (xm << 16) | (xn << 5) | xd` (`smulh x2, x0, x1` =
`0x9b417c02`, which `test_arm64_encoders.py` now checks against `as`). The
nearest branch is `_STEP_CONDS[4]`, `MUL` at `(0xffe07c00, 0x9b007c00)`, whose
mask clears bits 23:21 — and `SMULH` is that word with **bit 22 set** (the S
bit, which on this class means "the high half" rather than "and set the flags").
So the mask does not match and `arm64_step` answers `none`.

## Why it is a hole and not a decision

`formal/model.py::int_overflow_traps` is the decision that wants this
instruction: `MUL` alone cannot answer "did `a * b` fit in 64 signed bits",
because a wrapping `MUL` and a fitting one produce the same word. `MUL` +
`MSUB` would answer it; `SMULH` answers it in one instruction, and
`formal/arm64_codegen.py` emits it. There is no example in
`formal/examples/*.mojo` whose image contains it (the census's EX column reads
`0 ex` for this row), so no proof is blocked *today* — which is exactly why it
survived: the same "an encoder nothing exercises is not a gap" reasoning the
census exists to correct.

## The exact next step

The same four things the `TBZ`/`TBNZ` wiring cost, and
`bugs/FORMAL_arm64_instruction_coverage.md` §"The two largest gaps are now
closed" is the worked example:

1. `lib/ProofLib.lean`: one branch in `arm64_step`, appended at the END of the
   if-chain (every index above 53 is hard-coded in `_step_rhs` and in the block
   scanner). The mask must keep bit 22 — `(0xffe07c00, 0x9b407c00)` — or it
   collides with `MUL`.
2. `formal/arm64_proof_gen.py`: the `_STEP_CONDS` row, `_step_rhs` and
   `_step_rhs_generic` arms, and the block-scanner entry.
3. `lib/ProofLib.lean`: a `work_step_smulh` theorem, plus an `hne_smulh` fact
   in **every one of the 18 `work_step_*` theorems** that negate the branches
   before their own. This is the part that is not cheap and the part that made
   the `CSEL` wiring a documentation exercise rather than a change.
4. `python3 tools/formal_model_fuzz.py --mix flagged --cases 200` — the mix
   already draws it, so this is the measurement that says the arm is right.

The fuzz pool side needs nothing: `tools/formal_model_fuzz.py`'s
`gen_flagged_alu` emits `smulh` today, so the gap is visible on the next sweep
as a `NOSTEP` rather than as silence.