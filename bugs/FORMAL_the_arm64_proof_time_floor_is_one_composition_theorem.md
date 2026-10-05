# The arm64 proof-time floor after the step-OK swap is ONE declaration: `compiles_correctly_universal`, at 83% of the file

**Class:** performance. **Area:** `formal/arm64_proof_gen.py`'s CFG walk
terminal-value-flow and glue emission (`generate_arm64_proof`'s `step_tests`
/`compiles_correctly_universal`, and the per-path `have hpcb_/hcbz_/hs_/hg_`
chains), against `lib/ProofLib.lean`'s `arm64_go_exit` and `lib/work.lean`'s
`rec1_glue_gen` / `go_exit_step`. **arm64 only** — the x86-64 generator proves a
different thing over `lib/X86.lean` and shares none of this code.

**Status: OPEN, measured, NOT FIXED. Re-measured 2026-10-05 twice over: the
attribution HOLDS and is now re-derivable with a committed instrument, and
BOTH of the doc's remaining next steps are REFUTED — item 1's by a measurement
that is the shape it proposed, item 2's already was.** Below, in the order a
reader needs them:

* **THE PREFIX SWEEP IS IN THE TOOL, and it re-derives the attribution this
  document was written from.** `tools/formal_proof_shape.py --mode prefix` is
  what §"How to re-derive the table" said was missing ("it is NOT in the tool"),
  and on `formal/examples/bitops.mojo` it prints **346 top-level groups** and,
  checked at three of them:

  | prefix ends after | line | wall | cpu |
  |---|---:|---|---|
  | `bitops_prog` (group 342) | 3638 | **3.9 / 4.1 / 4.2 s** | 6.7-8.0 s |
  | **`bitops_compiles_correctly_universal` (group 343)** | 3643 | **21.8 / 21.9 / 22.1 / 22.6 / 23.4 s** | 27.9-30.2 s |
  | the whole file (group 346) | 3994 | **21.3 / 22.0 / 23.2 s** | 29.0-31.7 s |

  so **one declaration is +17.7 to +19.3 s of a 21-23 s file — 82-90 %**, which
  is the §"The measurement" table's claim re-measured by the instrument rather
  than by a `.tmp` script. The unit is a PREFIX and not a deletion because a
  prefix is always a valid Lean file and a deletion is not (§"How to re-derive
  the table" states the constraint; `declaration_starts`/`prefix_text` are where
  it is now kept). `--list-groups` prints the 346 boundaries with **no Lean run
  at all**, which is the half a reader wants first: the full sweep is 346 runs
  of 2-20 s.
* **ITEM 1's NEXT STEP IS NOT WORTH DOING, and the measurement is the shape it
  proposes.** §"What is actually left" item 1 says to state the terminal value
  flow as "one `{stem}_b{k}_x0` per block, proved from that block's own short
  `simp only` list, then compose the blocks with `rw`". Built and measured on
  the generated file — the block chain unfolded ONE `qS`/`qT` def at a time
  (83 `simp only` lines where there was one `simp +decide only`), each carrying
  that block's peelers, then one closing `simp +decide only` with no block defs
  — it elaborates (`rc 0`, no new `sorry`) and it is **SLOWER**:

  | the file | wall | cpu | `type checking` |
  |---|---|---|---|
  | as generated | **19.5-21.5 s** | 29.4-30.0 s | **7.8 s** |
  | the flow split into 83 per-def steps | **28.2 s** | **35.3 s** | **13.4 s** |

  `simp`'s own bucket does not move (8.4 s either way) and **type checking
  rises by 72 %**, so the cost of the decomposition is the ELABORATOR
  re-type-checking an intermediate term per step, which is a second-order term
  the one-big-`simp` version pays once. **So the answer to the question this
  document's own Status calls "the one link that is not measured" — is the cost
  the TERM or the pretty-print — is neither: it is not the `qS`/`qT` chain at
  all.** Measured directly, by re-checking the file with the block chain
  DELETED from the flow's `simp only` set (the chain kept out, everything else
  identical): **19.5 s against 20.7 s**, i.e. the whole cross-block chain is
  worth about a second of a 21-second file and the document's 7.8 s is
  elsewhere.
* **WHERE THE 7.8 s ACTUALLY IS: the MEMORY STORE STACK inside ONE block.**
  `--mode goal --which 1` reproduces the doc's own number (2 goals printed, the
  largest **23 856 chars / 307 lines**), and instrumenting the goal by hand says
  what fills it. The residual after unfolding **block b4 alone** — 30
  instructions, 11 frame stores, 2 distinct slot addresses — is

  | the `simp only` set | residual chars | `mem_write_u64` in it | `mem_read_u64` |
  |---|---:|---:|---:|
  | that block's own defs | **23 709** | **128** | 40 |
  | …plus the five `mem_read_after_write*` peelers | **17 481** | **88** | 20 |
  | …plus address canonicalisation as well | 17 482 | 88 | 20 |

  Every read re-embeds the store prefix under it, so an 11-store block hands
  `simp +decide only` a term with **128 `mem_write_u64` applications** in it.
  **The peelers already reduce it as far as they can and address
  canonicalisation adds nothing** (88 either way), so the lever is not a simp
  set: it is that this path has no per-block MEMORY WINDOW, the way
  `lib/Refine.lean`'s `FrameOk` already states one for a CALL — "the stores
  below `sp` do not change the caller's window" — which would let the flow read
  each of b4's two slots from `s_2.mem` instead of from the whole stack.
  **That is a `lib/ProofLib.lean` addition**, so it is the trade §"Do NOT start
  from raise the ceiling" and item 2 already name (it invalidates every
  worker's `.olean` cache) and it has to be made deliberately. It is the next
  step, and it is NOT the emitter.
* **`omega` was already refuted (item 2) and the LIBRARY route stands.** 0.17 s
  in the whole file, so the per-step fuel-arithmetic hoist cannot be 8.3 s. What
  remains of item 2 is unchanged and still a `lib/work.lean` lemma composing
  several `rec1_glue_gen` steps at once.

Everything below this is the analysis the document was written with, and it
stands: the measurement table, what is ruled out, and §"What is actually left"
— whose two items are both now measured out, above. The 2026-10-05 status
block this replaces is superseded rather than contradicted: its `omega` number
(0.17 s), its `--mode goal` residual (23 856 chars / 307 lines / 33 expanded
state literals) and its "the measurement below is CONFIRMED" line are all
reproduced above or in §"The measurement", and its one open question — whether
the cost is the term or the pretty-print — is answered.

## The measurement

`formal/examples/bitops.mojo`, arm64, one `lean` per file through
`formal/lean.py::run_lean`, on a machine running 8-16 other formal workers (so
the wall figures carry several seconds of noise; the CPU figures are the ones
to read). The instrument is a PREFIX sweep: the generated file is split at its
column-0 declarations and every prefix is re-checked, so the delta between two
prefixes is that group's own cost. A prefix is always a valid Lean file, which a
"delete this group" variant is not — the file stops elaborating and the timing
then measures Lean's error recovery, which is why the rows below are prefixes
and not deletions.

| prefix ends after | wall | CPU | delta |
|---|---|---|---|
| `*_runs_*`, `*_insn_*` | 0.8 s | — | — |
| all 53 `*_sr_*` (step RESULT) | 1.6 s | — | 0.8 s for 53 lemmas |
| all 53 `*_step_ok_*` (step OK) | 2.9 s | 5.8 s | 1.3 s for 53 lemmas |
| `*_compiles_correctly`, `blk_*`, `bitops_prog` | 3.9 s | 7.5 s | 1.0 s |
| **the whole file** | **19.5-20.8 s** | **26.6-29.0 s** | **16.1 s (83%)** |

The whole of that 16.1 s is **one declaration**: `bitops_compiles_correctly_universal`,
340 lines, the last in the file. Not the 51 block certificates before it (1.0 s
for all of them plus the `qS`/`qT` state functions), not the 53 step-RESULT
lemmas, not the 53 step-OK lemmas.

Within it, on the same instrument:

| what | wall | CPU | reading |
|---|---|---|---|
| whole file | 20.8 s | 26.6 s | |
| the 4 terminal value flows replaced by `sorry` (**measurement only**) | 13.0 s | 21.5 s | **7.8 s** in four `simp +decide only [...]` calls |
| the rest of the declaration | | | **8.3 s** in the walk's `have`/`rw`/`refine` chains |

`lean --profile` on the whole file agrees on the shape and names the buckets:
`blocked (unaccounted) 104s`, `simp 8.48s`, `type checking 8.24s`, `tactic
execution 4.17s`, `import` 0.64 s — so the library is not the cost and the
elaborator's own work is roughly half of it.

## What is ruled out, measured rather than assumed

Each of these was the obvious next suspect and each measured out as noise or as
a loss, so none of them is where the next hour goes.

* **The remaining `native_decide` calls are not the cost.** Rewriting all 53
  `have hinsn : arm64_read_insn <stem>_code <pc> = (<word> : UInt32) :=
  by native_decide` into the `{stem}_insn_{i}` lemma that already states
  exactly that (by `rfl`) changes nothing: 18.1 s -> 17.9 s wall, 26.9 s ->
  26.8 s CPU, inside the noise. `decide` in place of `native_decide` on the 262
  remaining closed-`UInt32` numeral facts is 18.4 s -> 17.9 s wall and 26.3 s ->
  23.0 s CPU: about 3% of CPU, not worth a second change on its own.
  `native_decide`'s per-call cost is amortised across the file by the
  elaborator's LCNF pass, so the COUNT of calls is not the cost.
* **Extending `lib/work.lean`'s `work_step_*` family is not the cost.** 247 of
  the corpus's 2 230 step-RESULT lemmas still take the discriminator route
  (`_step_facts`: 56 `native_decide`, `unfold arm64_step`, two `simp` passes)
  because step-table entries 14-17 and 36-53 have no `work_step_*` lemma.
  Replacing all three of `bitops`'s with `sorry` saves **0.5 s of 19.7 s**. Over
  the corpus that route is ~247 x 0.17 s = ~42 s across 49 files, under 1 s per
  file — and it would cost a `lib/*.lean` change, invalidating every worker's
  `.olean` cache, for a second-order win.
* **Per-call `simp` set construction is NOT the cost either, and this one
  corrects the obvious guess.** The terminal value flow names ~60 state
  functions plus ~20 `u64_*`/`mem_read_*` lemmas in ONE `simp +decide only`. The
  natural reading is that a `DiscrTree` over 80 rules is expensive to build four
  times. Splitting it into `simp only [<60 state functions>]` (pure delta) and
  `simp +decide only [h8, mojo, <20 rewrites>]` is **slower**: 21.8 s and 22.6 s
  on two runs against 19.0 s for the unsplit file, because two `simp` passes
  traverse the goal twice. So the rule count is not the lever and a "smaller
  simp set" is not the fix.

## What is actually left, and the next step

Two separable costs, both inside `compiles_correctly_universal`, and both
needing chunked composition rather than a cheaper tactic:

1. **7.8 s — the terminal value flow.** One goal per CFG path,
   `(s_k).x0 = mojo n`, where `s_k` is reached through up to 60 nested
   `{ _qT{i} st with … }` / `{ _qS{i} st with pc := … }` updates, and the proof
   unfolds the whole chain in a single `simp +decide only`. The file ALREADY has
   the chunked form for a neighbouring obligation — the back edge's register
   facts are built as "a CHAIN of shallow per-block facts (one block each), so
   the kernel never unfolds the deep chain" (the emitter's own comment, at
   `formal/arm64_proof_gen.py` near the `h{i}x{reg}` chain) — and the terminal
   value flow does not use it.
   **Next step:** state the terminal value flow the same way: one
   `{stem}_b{k}_x0 : ∀ st, (b{k}_qT{n} st).x0 = <per-block expression>` per block,
   proved from that block's own short `simp only` list, then compose the blocks
   with `rw`. That is a change to the value-flow emitter, and it is the single
   biggest remaining item in the arm64 proof path.
2. **8.3 s — the walk.** 114 `have`s, 62 `rw`s and 10 `refine`s of
   `rec1_glue_gen` / `go_exit_step` chains, per path. Same shape, same fix
   direction: the per-path `h_adv_{bi}` fuel-arithmetic rewrites
   (`show 30 + (200000 + 48 * n.toNat - 48) = … from by omega`, repeated at
   every step of every path) are a per-step re-derivation of one monotone
   fuel identity, and hoisting them into one lemma per path is mechanical.
   **THE HOIST IS NOT THE COST — MEASURED 2026-10-05, and this is the one
   thing in this document that has been refuted.** `omega` costs **0.17 s in the
   whole file** (`tools/formal_proof_shape.py --mode profile`, which sums the
   per-call lines; see the Status section), those rewrites are all of the
   `omega` there is, and 0.17 s cannot be 8.3 s. **So the fix for this item is
   not in the emitter at all: it is a `lib/work.lean` lemma that composes
   several `rec1_glue_gen` steps at once**, which is why §"What is ruled out"
   is right that the `lib/*.lean` route costs every worker's `.olean` cache and
   why that trade has to be made deliberately rather than by picking the
   mechanical-looking half.

**Do NOT start from "raise the ceiling".** `PROOF_WALL_S`/`PROOF_CPU_S` are
1500 s and nothing in the 49-example corpus comes near them; the file that hurts
is the biggest *generated* proof, and the fix for that is a smaller generated
proof. The one row where size did not predict cost (`formal/lean.py`'s module
docstring: `wide_recv` 703 KB in 93 s, `udivmod` 437 KB in 298 s before this
pass) is `udivmod`, which this pass took 52.9 s -> 29.6 s — so the ranking
itself moved, and a bound re-derived from the old one would be re-derived from
stale data.

## How to re-derive the table

The scratch scripts this section used to point at (`.tmp/genproof.py`, and a
prefix sweep that split the generated file at its column-0 declarations) are
gone with the next `.tmp` clean. **`tools/formal_proof_shape.py` replaces the
first and now answers the question the sweep was reaching for too**, and it
goes through `formal/lean.py::run_lean` for every Lean run, so nothing here
launches `lean` by hand:

```sh
export PATH=/opt/homebrew/bin:$PATH

# The buckets, ranked.  This is §"The measurement"'s `lean --profile` line and
# §"What is ruled out"'s `omega` number, and it sums the per-call lines, so
# `simp` is ONE row rather than eight.
python3 tools/memslot.py --gb 8 --label shape -- \
  python3 tools/formal_proof_shape.py formal/examples/bitops.mojo --mode profile

# What the terminal value flow is still trying to prove: the flow's `simp
# +decide only` becomes `trace_state` and the leaf is admitted, and Lean
# prints the residual goal.  `--which N` picks the Nth of the four.
python3 tools/memslot.py --gb 8 --label shape -- \
  python3 tools/formal_proof_shape.py formal/examples/bitops.mojo --mode goal --which 1

# WHICH GROUP of the file costs what — §"The measurement"'s table, re-derived.
# `--list-groups` prints the boundaries with no Lean run at all, so the sweep
# below costs three runs rather than 346.
python3 tools/memslot.py --gb 8 --label shape -- \
  python3 tools/formal_proof_shape.py formal/examples/bitops.mojo \
    --mode prefix --list-groups
python3 tools/memslot.py --gb 8 --label shape -- \
  python3 tools/formal_proof_shape.py formal/examples/bitops.mojo \
    --mode prefix --at 342,343,346

# …or by the NAME a reader has rather than the index a sweep needs; both
# resolve through the same code, so the two spellings cannot disagree.
python3 tools/memslot.py --gb 8 --label shape -- \
  python3 tools/formal_proof_shape.py formal/examples/bitops.mojo \
    --mode prefix --group-of bitops_compiles_correctly_universal

# The instrument's own text handling, with no Lean at all.
python3 test_formal_proof_shape.py
```

**The prefix sweep is `--mode prefix`, and the constraint that makes prefixes
(rather than deletions) the right unit is §"The measurement"'s and is now kept
in `declaration_starts`/`prefix_text`**: a prefix is always a valid Lean file
and a deletion is not, so "delete this group" measures Lean's error recovery.
Its other half is where a boundary goes — a declaration's FIRST line, counting
an `@[attr]` line or a `/-- … -/` doc comment that belongs to it, because
truncating between those leaves an attribute with nothing to apply to. For
`bitops` that is **346 groups**, so the full sweep is 346 runs of 2-20 s where
the five groups this document's table has are worth five: `--at` is how you say
which five.
