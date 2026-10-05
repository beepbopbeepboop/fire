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

## Status, 2026-10-03 (`formal13-3`): step 2 LANDED, step 1 is built and measured,
## and the cost centre is `_gen_run_cert`, not the block layer

Two measurements and one landed change. None of them re-verifies anything the
sections above say; the first two are new numbers and the third is a correct
answer to a question the "exact next step" left open.

### Step 2 landed: `_dylib_spec_lean` renders a conditional expression

`TernaryExpr`, `and`/`or` and a comparison read as a **condition** are now
rendered, so rows 3, 4 and 5 derive a spec instead of none. Each rendering is a
decision and is pinned with its EXACT string by `test_formal_dylib.py`'s
`a conditional expression derives a spec`:

* the ternary tests TRUTHINESS (`!= 0`), not equality with zero — which is what
  `_emit_csel_ternary` says in so many words ("`ne` rather than `eq` because
  Python's ternary tests the condition for TRUTHINESS");
* `and`/`or` select an OPERAND (`a and b` is `b` when `a` is non-zero), which is
  `_emit_truthy_word`'s rule and not a boolean;
* a comparison is rendered **SIGNED**, as `(a ^^^ SIGN) ⋈ (b ^^^ SIGN)` — the
  statement `arm64_flag_gt_s` makes, and measured: `(n if n > 3 else 0) * 3`
  answers 0 at `n = 2^63`, which is the signed reading. The sign mask is a
  literal because `bv_decide` works on literals (§2 of
  `FORMAL_dylib_export_loops_and_frame_bounds.md`).

Two shapes are still refused, and the refusals are asserted rather than left
implicit: a comparison in VALUE position (`return n > 3` — this path's only
word-shaped encoding of a bool is 0/1 by convention, not by a rule anything
states), and a compound condition (`if a and b`, which needs the short-circuit
two separately-inlined operands do not carry).

### Step 1 is a three-line change and it BUILDS — and it costs 14 GB

`CSEL` in `arm64_step` + `_STEP_CONDS` + one `_step_rhs` arm is exactly as
scoped above, and it works:

* **the mask.** `0xffe00c00`, not `0xffe00000`: bits 11-10 (`o2`) are what
  separate the four siblings on this base, and a mask without them answers for
  `CSINC` (`rn + 1`) and `CSNEG` and `CSINV` too. Measured against
  `as -arch arm64`: `csel x0, x0, x1, eq` is `0x9a810000`, `csel x3, x4, x5, gt`
  is `0x9a85c083`, `csinc x0, x0, x1, eq` is `0x9a810400` — the entry claims the
  first two and none of the other 51.
* **the position.** LAST in the chain, deliberately. A row's position is
  load-bearing only when its condition can match the same word as another's,
  and this one cannot (`audit_step_table` is green on it); put earlier it would
  sit in front of five `work_step_*` lemmas that negate every PRECEDING branch
  under a number that is its chain position, so inserting renumbers them and
  breaks five proofs for no gain. `lib/ProofLib.lean` rebuilt clean, 1m33s.
* **what it buys, measured.** Rows 4 and 5 of the table above go from "this
  export's run terminates" as a NAMED obligation to `DylibExport.total_of_halts`
  — PROVED, with the `tri_halts` walk lemma proved beside it.

**And it is not landable, because of row 3.** `return (n * 3) if n else 0` — 24
instructions, TWO FEWER than row 4, which passes — fails to check:

    row3_proof.lean:3200:8: error: (kernel) excessive memory consumption detected

at `dylib_export_0_tri_halts`, the walk theorem `_gen_run_cert` emits. Raised to
`-M 16384` under a 14 GB ceiling it was killed again, so this is a blowup and
not a marginal overshoot; baseline row 3 is 1.7 GB, post-change row 4 (26
instructions, also a CSEL) is 1.9 GB. So:

* **this is NOT the block layer.** `_dylib_contract_proof` still declines every
  one of these three — its own check is textual (`if any("if " in _body_of(i))`)
  and a CSEL's effect contains an `if` while writing no `pc`, which is the whole
  distinction the block layer cares about. The cost is upstream, in the walk.
* **`_gen_run_cert`'s `hx30` composition is the cost centre to attack.** It is
  the one goal in `tri_halts` that unfolds the WHOLE composed state — one
  `simp only [qS0 … qS23, qT0 … qT23, arm64_reg, arm64_set_reg, …]` followed by
  `simp (disch := decide) [mem_read_after_write_u64, …]`, over a term that now
  contains `arm64_matches_condition cond s.nzcv`. `disch := decide` then has to
  decide propositions about a 64-bit expression it cannot see through. The
  documentable fix is the same shape as §1 of
  `FORMAL_dylib_export_loops_and_frame_bounds.md` (fifteen `simp only` blocks
  re-unfolding the composed state → one per-step lemma): `x30` is written by
  `BL` and nothing else, so a per-step `rfl` ("this step's effect does not
  mention `x30`") composed by transitivity replaces the whole simplification.
  Measured negative already, so nobody re-tries it: adding
  `arm64_matches_condition` and `arm64_subs_flags` to that `unfold_terms` list
  changes row 3 by nothing measurable.
* **why it was not landed.** Modelled CSEL turns a NAMED OBLIGATION into a build
  FAILURE for a real program, which is strictly worse than the obligation, and
  the alternative — refusing a block that contains a conditional-value step —
  is a special case chosen to dodge a cost this emitter cannot model.

So the two halves of this document's headline now stand as measured: a ternary
really is not a branch (§1, re-confirmed by `csel x0, x0, x1, eq` being four
instructions and no control flow), and the block layer really is not the ceiling
— the ceiling for rows 3/4/5 is `_gen_run_cert`'s composed-state proof, and for
row 6 it is still the per-block `pc` function above.

## Status, 2026-10-04 (`formal29-2`): the block layer's OWN check is fixed, and it
## was refusing a shape the layer already expresses

The last bullet of the section above — *refusing a block that contains a
conditional-value step is a special case chosen to dodge a cost this emitter
cannot model* — is now **wrong, and the thing it describes was a defect in its
own right rather than only a workaround.** `_dylib_contract_proof`'s gate was

```python
if any("if " in _body_of(i) for i in range(m)):
    return ""
```

a substring test standing in for *one function of one state*, which is what
`Refine.Block.step` actually asks for. The two are different, both spellings are
real, and the substring cannot tell them apart:

| a step that CHOOSES A VALUE | a step that CHOOSES A PC |
|---|---|
| `CSET`: `some (arm64_set_reg rd s (if arm64_matches_condition c s.nzcv then 1 else 0))` — one `some`, so `arm64_step` says it is one function of one state | `B.cond`/`CBZ`/`TBZ`: the model answers `if c then some A else some B`, so there is no single `some` to strip |

So the check refused every export whose code contained a `cset`, which is a
**live, already-reachable** loss and not a hypothetical one about CSEL:

```
$ cat .tmp/p/csetval.mojo
def csetval(n):
    var b = not n          # CMP + CSET — branchless, two instructions
    var m = n * 3
    return m
```

`arm64_codegen.py` emits `cmp` + `cset` for a `not` in VALUE position
(`_emit_truthy_word`, then `encode_cmp_xn_imm` + `encode_cset_xd_cond`, ~line
5182) and never branches. The image is 23 instructions, the eighth is
`cset x0, eq`, and it computes `n * 3` — run through the dylib: 0/15/42/300 for
`n = 0/5/14/100`, against the same values from the branchless twin with the
`not` deleted. `_dylib_contract_proof` returned the **empty string** for it.

**The fix asks the MODEL's shape instead of the text.** `arm64_step` returns
`some <state>` exactly when the step is one function of one state, so `_step_rhs`'s
own `some` prefix is the discriminator — and it is the same prefix `_body_of`
already reads, so there is no new encoding to keep in step. The `pc_writes`
discipline below it is unchanged, so a branch in any position but the last is
still declined, and the last may still be the `ret`.

Measured after: the same export gets a **PROVED** contract — `bodyCert`,
`agrees_of_body`, `hreg` — and the emitted file checks clean with **0 holes** in
**7.5 s / 1.6 GB** through `formal/lean.py`. `test_formal_dylib.py`'s
`a conditional value is not a branch` pins all three claims: the image's answers,
a PROVED `agrees_of_body` for the `cset` export, and — the control — a *named*
`_spec` obligation and **no** contract for a body with a real `B.cond` in it,
whose spec is handed over by hand so that "a spec exists" and "a contract was
proved" are two facts in the same file. `test_formal_dylib.py` is 25/25.

### What this does and does not unblock

* **It does not make rows 3/4/5 build.** Those still need the `CSEL` row, and
  that row is not this document's: it is deliberately ABSENT from `_STEP_CONDS`
  with a long comment saying why (`check_step_conds` requires the table and
  `arm64_step` to be the same set, so a row here with no model branch is a
  generator describing a CSEL's effect while the function being proved takes no
  step for that word), and the model branch is claimed by
  `FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`
  (formal28-2), blocked on `FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`
  (formal28-1). What landed here is that when that row does arrive, the block
  layer will already accept it: a `CSEL` is `some (arm64_set_reg rd s (if … then
  … else …))`, which is the `CSET` shape above, one `some` around a conditional
  value and no `pc` write anywhere.
* **Row 6, the loop, is untouched** and still needs the per-block `pc` function.
* **The `_gen_run_cert` cost centre is untouched** and is not this document's
  either — it is the three-branch certificate's, on formal28-1's claim.
