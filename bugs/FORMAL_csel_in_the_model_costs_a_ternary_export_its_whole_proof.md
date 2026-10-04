# A `CSEL` in a dylib export makes `_gen_run_cert`'s termination walk cost
# over 14 GB, so a ternary export fails to build a proof instead of naming an
# obligation

**Area:** FORMAL — the dylib export walk, `formal/arm64_proof_gen.py`'s
`_gen_run_cert` (the `qS`/`qT` per-step chain and the `hx30` goal it composes).
Found 2026-10-03 on `work/formal13-3` while doing the `CSEL` step that
`bugs/FORMAL_dylib_block_layer_is_not_the_ceiling.md` §"The exact next step"
prescribes. **OPEN, measured, NOT fixed here** — and it is the reason that step's
CSEL model row is not landed even though it is three lines and it builds.

**Re-read 2026-10-03: nothing here has moved, and the OWNERSHIP has.** The CSEL
model row is `formal16-2`'s (`bug:FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`,
whose §next step names this doc as the blocker), so what this doc owes is the
COST half and the modelling half is not duplicated here. Re-confirmed on this
tree, cheaply, without a Lean run:

* `_STEP_CONDS` has **no** CSEL row and `arm64_step` has no CSEL branch, and the
  comment where the row used to be says why the row is absent rather than
  missing — so the "modelling it costs 14 GB" claim is still the reason it is
  unlanded, not a stale memory of one experiment;
* the `hx30_{bi}` goal is still the whole-chain shape §"Where the cost is"
  quotes, verbatim: `simp only [qS…, qT…, arm64_reg, arm64_set_reg,
  Arm64State.init]` then `simp (disch := decide) […]` over the composed state;
* the technique the next step prescribes is in the file and unchanged —
  `hpc_{bi}` at the top of a run is `by rfl` when the pc is decided, and
  `hpc_s_{bi}` is its sibling for the composed state.

**What HAS changed is what it costs to find out.** The eight Lean-checking
formal gate tests are disabled, so nothing measures this any more; and
`lib/ProofLib.olean`'s build peaks at **7.82 GB** (`formal/lean.py`'s own
measured table), so a light worker with an 8 GB ceiling cannot rebuild the
library at all — and re-measuring this doc's 14 GB number needs a `MEMLIMIT_GB`
above 8. Anyone picking this up should budget for that rather than discovering
it at the end.

## What I ran

Six export bodies, each built as its own dylib with `fire.py dylib --formal`
(so the contract AND the termination proof are both emitted), on this tree, with
`CSEL` present in `arm64_step` / `_STEP_CONDS` / `_step_rhs`:

| body | instructions in the export extent | verdict |
|---|---|---|
| `return n * 3` | 15 | `total_of_halts` — proved |
| `return (n * 3) and (n + 1)` | 26 | `total_of_halts` — proved, 1.9 GB |
| `return (n if n > 3 else 0) * 3` | 26 | `total_of_halts` — proved |
| `return (n * 3) if n else 0` | **24** | **`error: (kernel) excessive memory consumption detected`** |
| `var i = n` / `while i > 0: i -= 1` / `return i * 3` | 27 | NAMED obligation (unchanged — a loop is not one block) |

The failing body is the SHORTEST of the four that reach the walk, and the
failure is not a marginal overshoot:

```console
$ python3 fire.py dylib --formal -o row3.dylib row3.mojo
formal dylib: proof check failed: row3_proof.lean:3200:8: error: (kernel)
excessive memory consumption detected
```

`3200` is `dylib_export_0_tri_halts`, the walk theorem `_gen_run_cert` emits.
Re-run outside the gate with `lean -M 16384` under a 14 GB ceiling, it was killed
again. Baseline for the same body before `CSEL` was modelled: 1.7 GB and one
named obligation, exit 0.

**So modelling `CSEL` turns a NAMED OBLIGATION into a BUILD FAILURE**, which is
strictly worse than the obligation it replaces. That is the whole reason the row
is not landed, and it is not fixable by raising `-M`: this is a blowup, not a
budget question (the same argument §1 of
`bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` records for `hreg`).

## Where the cost is

Inside `tri_halts` there is exactly one goal that unfolds the WHOLE composed
state — `hx30_0`:

```lean
have hx30_0 : (dylib_export_0_tri_walk_b0_qS23 ({ Arm64State.init n … })).x30
    = UInt64.ofNat 4294967984 := by
  simp only [dylib_export_0_tri_walk_b0_qS0, …, dylib_export_0_tri_walk_b0_qT23,
             arm64_reg, arm64_set_reg, Arm64State.init]
  simp (disch := decide) [mem_read_after_write_u64,
                          mem_read_after_write_u64_ne,
                          mem_read_two_writes_same]
```

Before `CSEL` that term is a straight-line nest of record updates, so the
simplification is cheap. After it, the term contains

```lean
if arm64_matches_condition 0 s.nzcv then arm64_reg 0 s else arm64_reg 1 s
```

with `s` the composed state, and `simp (disch := decide)` is now asked to decide
propositions about a 64-bit condition it cannot see through. `disch := decide` is
the load-bearing word: it is there so a *decidable* side condition closes the
goal, and the alternative — leaving the condition opaque — makes the whole
`if`-chain unresolvable.

**Measured negative, so nobody re-tries it.** Adding `arm64_matches_condition`
and `arm64_subs_flags` to that `unfold_terms` list (so the condition is a
literal `if 0 = 0 then … else …` and reduces immediately) changes row 3 by
nothing measurable: same error, same three sites, 6.1 GB peak. The cost is not
the condition's shape; it is that a conditional VALUE makes the composed state a
function of the flags, and every later `simp` goal now has to carry that.

The two bodies that pass differ from the one that fails in which condition code
they use: row 3's is `csel x0, x0, x1, eq` (code 0, `z = 1`) and row 4's is
`csel x0, x16, x0, ne` (code 1, `z = 0`). Neither the difference nor a
threshold is characterised; nothing here should be read as "row 3 is over the
line and row 4 is under it" — both are within a factor of a couple of
instructions of each other and the margin is not understood.

## The next step, and it is the same shape as §1 of the sibling document

Make `x30`'s invariance a PER-STEP fact instead of a whole-chain simplification.
`x30` is written by exactly one modelled instruction (`BL`, `_regs_written`'s
`{30}`) and by nothing else, so for every step of a block that has no `BL` the
statement `(qT_i (qS_i st)).x30 = (qS_i st).x30` is `rfl` — `arm64_set_reg k s v`
leaves `x30` alone for every `k ≠ 30` by construction. Compose those per-step
`rfl`s along the block and `x30`'s value never leaves the start state, so the
`simp only […23 qS, …23 qT…]` disappears from this goal entirely and the walk's
cost stops depending on how conditional the body's VALUES are.

That is the identical move §1 records: fifteen `simp only` blocks re-unfolding
the composed state became fifteen `omega`s off one per-step `pc` lemma, and the
per-step `pc` lemma is what made `arm64_runs`'s own `if` resolvable. The `hx30`
goal is the last place in this walk that still re-unfolds the whole chain, and
it is the only one left.

**What to check before starting**, so the next reader does not re-derive it:

1. `formal/arm64_proof_gen.py`'s `is_ret` arm in `_gen_run_cert` (the `hx30_`
   emission, and its `unfold_terms` / `flow_hsid` / `flow_defs` machinery) —
   that is the code to change, and the per-step lemma has to be emitted where
   `qT_i` is defined rather than at the goal. Re-confirmed in place 2026-10-03.
2. `test_formal_dylib.py` in full: it is the file that proves the dylib path, and
   its "default path emits a checked proof" case is the one that would catch a
   per-step lemma that is `rfl` for the wrong reason. **It is one of the eight
   Lean-checking formal gate tests, which are DISABLED** — so running it is now a
   deliberate act rather than something the gate does for you, and it needs a
   `MEMLIMIT_GB` above 8 for the library build.
3. `hpc_{bi}` is the same shape of goal one field down and is already cheap
   (`by rfl`), so the technique is in the file; it is the `hx30` goal that pays
   for the whole chain.
4. **And the dependency runs the other way**: `formal16-2`'s
   `FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md` §3
   lists this doc as the thing to solve before the CSEL model row can land. So
   this is on the critical path of a claim somebody else holds, which is why it
   is worth the `MEMLIMIT_GB` rather than waiting for a quieter machine.
