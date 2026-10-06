# A `CSEL` in a dylib export makes `_gen_run_cert`'s termination walk cost
# over 14 GB, so a ternary export fails to build a proof instead of naming an
# obligation

**Area:** FORMAL — the dylib export walk, `formal/arm64_proof_gen.py`'s
`_gen_run_cert` (the `qS`/`qT` per-step chain and the `hx30` goal it composes).
Found 2026-10-03 on `work/formal13-3` while doing the `CSEL` step that
`bugs/FORMAL_dylib_block_layer_is_not_the_ceiling.md` §"The exact next step"
prescribes. **OPEN, measured, NOT fixed here** — and it is the reason that step's
CSEL model row is not landed even though it is three lines and it builds.

**Status 2026-10-04 (`work/formal16-4`): the `hprior` SHARING this document
identifies as the thing to land first is LANDED and MEASURED, and it is worth
80x fewer facts at five branches (§"What landed"). The `CSEL` model row itself
is still `formal16-2`'s and is NOT landed — this document's own §"the dependency
runs the other way" is unchanged, and it is still the case that landing it needs
the certificate to fit, which is a Lean run neither this branch nor the previous
passes could make.**

**What landed, and what it measured** (`formal/arm64_proof_gen.py`'s per-path
memo, no Lean needed to measure it — this document's §"What HAS changed is what
it costs to find out" is the reason):

| conditional branches | `hprior_*` before | after | proof lines before | after |
|---:|---:|---:|---:|---:|
| 2 | 48 | **24** | 6 942 | 6 822 |
| 3 | 144 | **48** | 10 130 | 9 650 |
| 4 | 384 | **96** | 15 814 | 14 374 |
| 5 | 960 | **192** | 26 762 | 22 922 |

The growth per branch goes from x3.0 / x2.67 / x2.5 to **x2.0**, which is the
number of PATHS — the part that is not re-derivation — and the distinct
statements are unchanged at 6 / 8 / 10 / 12. **The 80x is the ceiling and it is
NOT reached, and the reason is this document's own subject matter seen from the
other side:** cross-path sharing is unsound, because `s_{pb}` is REBOUND per
path (`hsid_{pb}` is emitted once per visit: 1 / 2 / 4 / 8 / 16 times for blocks
0 / 2 / 4 / 6 / 8 of the three-branch program), so a fact about `s_8` proved on
one path is about that path's `s_8`. The memo is therefore a per-block copy of
`ctx`, and `test_formal_call_proof_gen.py`'s `TestNestedConditionFactSharing`
holds it to that: one check fails if a fact is proved twice in a scope, one if a
fact is USED where it was not proved (which is what a memo shared between
siblings looks like), and one if the growth goes above x2.2 again. All three were
verified by disabling the memo and by sharing it globally, and the last one
reports this document's own numbers when it is disabled.

**So what this document's cost analysis now says.** The exponential it measures
was `paths x prior-blocks x variables`, and one factor of that was
re-derivation; the other two are the proof's actual shape. A three-branch
program's certificate is still eight paths through the CFG, each needing its own
`hcond_*` goal (28 of them) and its own `hx30_*` (32), and the `hcond_*` goals
are what `§2 of bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`
measured at 103 s / 4.2 GB with `maxHeartbeats` at 2 000 000. **Whether the
sharing is enough to let a three-branch export build a proof is NOT measured and
cannot be from here** — the table above is emission, and the certificate's cost
is the kernel's.

## The status this document had before

**The PRESCRIPTION in §"the next step" is measured to be aimed at the
wrong goal, 2026-10-03.** Everything this doc assumes about where the cost lives
was checked against the generated proof on this tree, and the `hx30` goal this
doc says is "the last place in this walk that still re-unfolds the whole chain"
is inside a **23.1-second, 2.5 GB** check of everything up to the final theorem.
The cost is the `hprior_*` value-flow facts, which are exponential in the number
of conditional branches and which this doc never mentions. §"The measurement
that decides it" has the numbers and what they say about the CSEL row; the model
row's own half is still `formal16-2`'s, as below.

**Re-read 2026-10-03 (second pass): nothing about the MODEL side has moved, and
the cost half now has a measurement that is not the one this doc predicted.**

* `_STEP_CONDS` has **no** CSEL row and `arm64_step` has no CSEL branch, and the
  comment where the row used to be says why the row is absent rather than
  missing — so the "modelling it costs 14 GB" claim is still the reason it is
  unlanded, not a stale memory of one experiment;
* the `hx30_{bi}` goal is still the whole-chain shape §"Where the cost is"
  quotes, verbatim: `simp only [qS…, qT…, arm64_reg, arm64_set_reg,
  Arm64State.init]` then `simp (disch := decide) […]` over the composed state —
  **and it is also still CHEAP**, which is the new fact and the reason the §"next
  step" below should not be followed as written;
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

## The measurement that decides it, and it is not this one (2026-10-03)

Taken on this tree against a generated three-conditional-branch proof, through
`formal/lean.py::run_lean`, under an 8 GB ceiling. The full method is in
`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md` §2 and §6;
what belongs here is what it says about the prescription below.

| what | result |
|---|---|
| the generated proof with the final theorem REMOVED — every block cert, every `qS`/`qT` chain, **all 32 `hx30` goals**, all 144 `hprior` goals' statements | **rc=0, 23.1 s, 2.5 GB** |
| the theorem's STATEMENT alone, on top of that | rc=0, 22.1 s — `runProg`'s reduction is free |
| the whole file | kernel OOM at 6.1–6.4 GB, 202–299 s |

**So the `hx30` goal is not where the 14 GB goes.** All thirty-two of them, each
one the whole-chain `simp only […qS0, …qT23, …]` this doc quotes, are inside
23 seconds. Rewriting them as per-step `rfl`s — the move §"the next step" and its
sibling §1 of `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` both
prescribe, and which this doc calls "the identical move" — would be real work
against a goal that is not the cost.

**What is the cost, and it has nothing to do with `CSEL`.** The generated proofs
of four programs differing only in their number of `if`s, counted with the proof
check stubbed out so no Lean run is involved:

| branches | `hprior_*` | `hx30_*` |
|---:|---:|---:|
| 2 | 48 | 16 |
| 3 | **144** | 32 |
| 4 | **384** | 64 |
| 5 | **960** | 128 |

`hprior` grows ×3.0, ×2.67, ×2.5 per branch — the only row that is not a doubling
— while `hx30` merely doubles. The `hprior_*` facts are emitted at
`formal/arm64_proof_gen.py:6143`, once per (PATH, prior block, variable), each
proved by unfolding that block's whole composed state. **A conditional VALUE
(`CSEL`) makes the composed state a function of the flags, so it makes EVERY one
of those facts more expensive — but it does not make more of them, and there are
already 9 of them per `hx30` at three branches without any `CSEL` in the image.**

**What this does to the CSEL row, precisely.** This doc's premise was "modelling
`CSEL` turns a NAMED OBLIGATION into a BUILD FAILURE". That is still what the
five-row table measured, and the row is still `formal16-2`'s to land. What
changes is the reason it is expensive: it is not that the `hx30` chain becomes
unresolvable, it is that a conditional value makes each of the already-exponential
`hprior` simplifications carry one more case. So **the thing to land before the
CSEL row is the `hprior` sharing**, and the thing that doc should be read
together with is
`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md` §3 and §5 —
a 24-instruction export with no `CSEL` in it at all already fails the same way.

## The next step as it was written, and why not to follow it

**Kept verbatim below, because the reasoning is correct and the target is wrong,
and both of those are worth being able to see at once.** Do not read it as a
prescription; read it as the shape of a fix once `hprior` is no longer the cost.

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
per-step `pc` lemma is what made `arm64_runs`'s own `if` resolvable. The claim
this doc ends on — "the `hx30` goal is the last place in this walk that still
re-unfolds the whole chain, and it is the only one left" — **is false**, and the
§"measurement that decides it" table above is what says so: `hprior`'s proofs
are `simp only [_pb_defs …]` over a composed state too, there are nine of them
per `hx30` at three branches, and they are the ones the kernel runs out of
memory on.

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
