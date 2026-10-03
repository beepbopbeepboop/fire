# The block layer is NOT the ceiling on a dylib export's proved contract, and a
# ternary is not a branch

**Area:** FORMAL (the dylib contract emitter). **Status: OPEN, measured, not
started.** Found 2026-10-03 while landing
`FORMAL_dylib_several_exports_have_no_proved_contract` (**deleted on
2026-10-03**), whose "also found" section scoped the remaining gap as a
scheme extension to `Refine.Block`.

## What I ran

Six one-`return` export bodies, each built as its own dylib
(`fire.py dylib --formal --no-prove`), then read three ways: the spec
`_dylib_spec_lean` derives from the source; whether `_dylib_contract_proof`
emits a `Block` + `BlockCert` + `atExit` for the block, **with the spec supplied
by hand** so that a refusal could not be spec derivation hiding itself; and how
many conditional `pc`-writes the emitted code actually contains.

## What I saw

| body | spec derived | contract with the spec supplied | why the contract declines |
|---|---|---|---|
| `return n * 3` | yes | **PROVED**, 15 instrs | — |
| `var m = n * 3` / `return m` | **no** | **PROVED**, 17 instrs | spec derivation only |
| `return (n * 3) if n else 0` | no | refused, 24 instrs | `CSEL` at step 19 — **0 branches** |
| `return (n * 3) and (n + 1)` | no | refused, 26 instrs | `CSEL` at step 21 — **0 branches** |
| `return (n if n > 3 else 0) * 3` | no | refused, 26 instrs | `B.cond` at 11, `CSEL` at 16 |
| `var i = n` / `while i > 0: i -= 1` / `return i * 3` | no | refused, 32 instrs | `B.cond` at 13, backward `B` at 21 |

Two corrections to what the deleted document believed, and the first is the
useful one.

**The `Refine.Block` layer was not the ceiling, and a conditional EXPRESSION is
not a branch.** The deleted document scoped its remaining work as "the block
layer needs a per-block `pc` FUNCTION rather than a literal address list, which
is a change to `Refine.Block` and `BlockCert` and to every emitter that uses
them". Measured: rows 3 and 4 contain **zero** conditional branches, and row 2 is
plain straight-line code for which the emitter emits a complete certificate
today. A ternary compiles to `CSEL` (`encode_csel_xd_xm_cond`,
`formal/arm64.py:857`, base `0x9A800000` — `0x9a811000` is `CSEL X0, X0, X1, EQ`),
which is one function of one state and exactly what `Refine.Block` expresses.
So the scheme extension is needed only for row 6.

**The ceiling was `_dylib_spec_lean`, 30 lines of Python in front of the proof
layer**, which required the body to be EXACTLY one `ReturnStmt`. That is now
widened to a chain of bindings to fresh names plus the `return`, and the
widening is Lean-checked: `one_local`/`two_locals` get proved contracts with 0
holes (`test_an_export_that_binds_a_local_still_gets_a_proved_contract`). Row 2
is closed by that change.

**Rows 3 and 4 are blocked on `CSEL` being absent from the machine model, not on
`Refine`.** `grep -c 0x9a8 lib/ProofLib.lean` finds nothing, and
`_step_branch_index(0x9a811000)` and `_step_branch_index(0x9a801020)` both
return `None`, so `_step_rhs` is never called and `_dylib_contract_proof`
declines before it looks at the body. This is a **coverage** gap and not a
wrong-answer one: the compiled path is right, checked by running it —
`return (n * 3) if n else 0` gives 0/15/21 for `n = 0/5/7`, which is CPython's
answer.

## What I expected

Some part of the block layer to be the binding constraint, because a body with a
branch really is not "one function of one state" and that argument is correct as
far as it goes.

## The exact next step

1. **`CSEL` in `arm64_step` and `_STEP_CONDS`**, and the four siblings already
   encoded in `formal/arm64.py` while it was there: `CSINC` (`0x9A800400`),
   `CSINV` (`0xDA800000`), `CSNEG`. They are pc-preserving and single-effect, so
   each is one row in `ProofLib.arm64_step` plus one row in `_STEP_CONDS` plus
   one `_step_rhs` arm, and `bv_decide` discharges the rest. Check
   `bugs/FORMAL_arm64_instruction_coverage.md` first — it is the survey of the
   ENCODER side and may already say where the model side stands.
2. **Then the second `_dylib_spec_lean` step, which is EXPRESSION-level** and
   independent of (1): `IfExp`, `and`/`or`, a comparison as a value. The
   statement-level widening that just landed does none of that, which is why
   rows 3 and 4 still derive no spec.
3. **Row 6, the loop**, is the only shape that genuinely needs the per-block `pc`
   function. Read `formal/arm64_proof_gen.py`'s main-path walk first: it already
   handles branches with a different structure (`qS`/`qT` plus a `self{i}` lemma
   per block address) and may already have most of it.
4. Keep every refusal a refusal. A shape the emitter cannot render must produce
   **no claim**: the only spec available without one is `fun n => n`, and that
   is false for every export in the tree that is not the identity.