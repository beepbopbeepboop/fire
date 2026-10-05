# FORMAL_arm64_ieee754_has_no_step_arms: ten IEEE-754 encoders the emitter calls, and no `arm64_step` arm

**Found 2026-10-05 by `tools/formal_isa_census.py`**, the instruction-coverage
census: `formal/arm64_codegen.py` emits ten scalar IEEE-754 binary64
instructions, every one of them has a byte-exact `as` differential in
`test_arm64_encoders.py`, and `lib/ProofLib.lean`'s `arm64_step` has **no branch
that matches any of their words** — so `arm64_step` answers `none` for all of
them, and a `double` in a proved program is a `NOSTEP` rather than a proof.

## What I ran

```
$ python3 tools/formal_isa_census.py --arch arm64 | grep -E "encode_f|encode_scvtf"
   encode_fadd_dd_dn_dm           NO   NO   yes  0 ex:   arm64_codegen.py x1 | BACKLOG: …
   … fsub, fmul, fdiv, fneg, fcmp, fmov_gpr_to_v, fmov_v_to_gpr, scvtf_dn_xn, fcvtzs_xn_dn
```

Call sites, for the record (`grep -n encode_f… formal/arm64_codegen.py`):
`fmov_gpr_to_v`/`fmov_v_to_gpr` at 3634-3636 (the `+0.0` idiom), `fcmp` at 7534
and 7780 (the floating comparison `formal/model.py` decides with), the four
arithmetic ops at 7569-7578, `scvtf` at 8446 and `fcvtzs` at 8458 (the int →
double and double → int conversions).

## Why the survey did not already say so

`bugs/FORMAL_arm64_instruction_coverage.md` describes the encoder table as
"the arithmetic that has to reach the FP unit for a `double` to round at all",
added under the same heading as the integer work — but its coverage numbers are
a rank over MNEMONICS in disassembled system binaries, and its tail is dominated
by NEON/FP, which the survey calls "the class this backend has no use for on a
target that is int-only (`formal/types.py` is the authority on that)". That
sentence is now FALSE for arm64: the emitter calls these ten encoders, so
floating-point arithmetic is emitted, and `formal/types.py`'s int-only reading
is a statement about what was true when the survey was written.

The LEAN column is the census's contribution: it asks the MODEL, per encoder,
and the model's answer is `none`.

## Two halves, and they are different sizes

**The FUZZ half is a harness limit and is permanent as written.**
`tools/formal_model_fuzz.py` installs X0-X30, SP, NZCV and a memory window, and
dumps the same. There is no V register file at all, so even with model arms
there would be nothing to compare: a `double` lives in D0-D7 and the two engines'
FP state cannot be placed side by side by this harness. Adding one means a
second state array in the `CaseIn`/`Case` structures, the stub, the epilogue and
the comparison — a real change to the harness the whole tree trusts, and not one
to make while hunting a model gap.

**The LEAN half is the model, and it is the expensive one.** `lib/IEEE754.lean`
models the ARITHMETIC at the value level (`faddBits`, `fdivBits`, `unordered`,
`canonicalQuietNaN` and the comparison lemmas), so the semantics exist — but a
`Arm64State` has no FP registers, so there is nothing for them to be semantics
*of*. The work is:

1. `Arm64State` gains D0-D7 (or a V-file slice) and the memory window stays as
   it is;
2. `arm64_step` gains one branch per opcode, each reading its V register and
   writing either a V register or NZCV — and `FCMP`'s flags are the interesting
   one, because an UNORDERED compare is not the integer compare: `lib/IEEE754.
   lean`'s `unordered`/`key` are the answer, and `V = 0` on unordered is a
   decision a C `double` comparison actually depends on;
3. `formal/arm64_proof_gen.py`'s `_STEP_CONDS` and `_step_rhs` gain ten rows —
   **appended**, never inserted, because every index above 53 is hard-coded in
   `_step_rhs` and in the block scanner;
4. `lib/ProofLib.lean` gains ten `work_step_*` lemmas AND an `hne_*` fact in
   every one of the 18 existing `work_step_*` theorems, exactly as the `TBZ`/
   `TBNZ` wiring did (`bugs/FORMAL_arm64_instruction_coverage.md` §"The two
   largest gaps are now closed", step 4, which is the one that costs).

**The order matters, and it is not the interesting one.** Step 1 alone would let
the harness compare; steps 2-4 alone would let a proof step the instruction. A
proof needs 2-4 and does not care about the harness, so that is the sequence;
the harness work is what makes the DIFFERENTIAL possible, and it is cheaper.

## The exact next step

Start with `FCMP` alone, not the arithmetic: it is the one whose absence is
visible in a source-level decision (`formal/model.py`'s floating comparison
leans on the unordered case), it is one branch rather than four, and it has the
flags to get right rather than a register. One branch end to end — `Arm64State`
field, `arm64_step` arm, `_STEP_CONDS` row, `work_step_fcmp` plus the 18 `hne_`
facts — is the smallest version of this that proves the approach, and the census
will say `LEAN: yes` for that one row when it lands.