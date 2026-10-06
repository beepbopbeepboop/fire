# The arm64 proof-time floor after the step-OK swap is ONE declaration: `compiles_correctly_universal`, at 83% of the file

**Class:** performance. **Area:** `formal/arm64_proof_gen.py`'s CFG walk
terminal-value-flow and glue emission (`generate_arm64_proof`'s `step_tests`
/`compiles_correctly_universal`, and the per-path `have hpcb_/hcbz_/hs_/hg_`
chains), against `lib/ProofLib.lean`'s `arm64_go_exit` and `lib/work.lean`'s
`rec1_glue_gen` / `go_exit_step`. **arm64 only** — the x86-64 generator proves a
different thing over `lib/X86.lean` and shares none of this code.

**Status: OPEN, measured, NOT FIXED. Re-measured 2026-10-05
(`work/formal29-5`) and the attribution HOLDS, item 2's stated next step does
NOT, and the instrument is now in the tree.** Below, in the order a reader needs
them:

* **`tools/formal_proof_shape.py` landed**, and every number in this document is
  now re-derivable with one command instead of a `.tmp` script:
  `--mode profile` is the ranked `lean --profile` (so the buckets are a list,
  not a wall of text), `--mode goal` prints what the terminal value flow is
  still trying to prove by replacing it with `trace_state` and admitting the
  leaf. `test_formal_proof_shape.py` covers the text handling without Lean.
  The two numbers this document's scratch scripts took are the tool's two
  modes.
* **The measurement below is CONFIRMED on this tree** (bitops, arm64):
  wall **19.9 s**, cpu **27.9 s**, `simp` **7.0 s**, type checking **7.0 s** —
  inside the ranges §"The measurement" gives (19.5-20.8 / 26.6-29.0, 8.48, 8.24).
  Nothing has moved, so the percentages here still apply.
* **ITEM 2's NEXT STEP IS NOT WORTH DOING, and the measurement is one line.**
  `--mode profile` reports `tactic execution of Lean.Parser.Tactic.omega` at
  **0.17 s in the whole file** — 0.9% of 19.9 s — and that is the ceiling on
  what hoisting the per-step fuel-arithmetic `show … from by omega` rewrites
  into one lemma per path can save, because those rewrites are all of the
  `omega` this file runs. The 8.3 s §"What is actually left" attributes to the
  walk is therefore NOT in the fuel arithmetic, and the `lib/work.lean`
  composition route stays the only thing that addresses it.
* **WHAT THE EXPENSIVE TACTIC IS PROVING, measured, is LARGE.** `--mode goal
  --which 1` prints **two** goals (not one: `trace_state` prints one state per
  goal the combinator hands it, and a tool that returned the last one reports
  the wrong goal by an order of magnitude — that was this session's first
  version, and the test now pins it), and the larger is **23 856 characters,
  307 lines, and 33 fully-expanded 31-field `Arm64State` literals**. So the
  `simp +decide only [107 names]` is being asked to traverse a term of that
  shape, which agrees with §"What is ruled out" having measured that the rule
  COUNT is not the lever.
* **THE ONE LINK IN THAT IS NOT MEASURED, and it is the thing a worker should
  measure first**: the 33 literals are how Lean PRINTS the goal, and Lean
  zeta-expands `{st with pc := p}` into all 31 fields when it pretty-prints. So
  "the elaborated TERM is that large" is NOT established — `lib/ProofLib.lean`
  has `[simp] theorem arm64_reg_pc (j) (s) (p) : arm64_reg j { s with pc := p }
  = arm64_reg j s`, which exists precisely so the rewrite never has to expand
  the structure, and the walk's states are `qS`/`qT` defs over such updates.
  **Whether the cost is the term or the pretty-print is the difference between
  "decompose the value flow" (item 1, below) and "stop re-stating the state",
  and it is a cheap measurement**: compare `--mode profile` on the file as
  generated against the same file with the `qS`/`qT` chain replaced by opaque
  `have`s of the same statements — a proof that is a chain of equalities rather
  than one big `simp` — which is item 1's shape anyway.

The rest of this document is unchanged and is still the analysis it was.

**Status: OPEN, measured, NOT FIXED.** Filed from `work/formal24-proof-speed`
immediately after landing the step-OK derivation (commit `6b1ddbe0`), which is
what produced the attribution below. This doc is the *remainder* of that pass,
not a duplicate of it: the step-OK layer is gone (`formal/examples/bitops.mojo`
33.8 s -> ~18 s) and this is what is left.

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
first and answers the question the sweep was reaching for**, and it goes
through `formal/lean.py::run_lean` for every Lean run, so nothing here launches
`lean` by hand:

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

# The instrument's own text handling, with no Lean at all.
python3 test_formal_proof_shape.py
```

A prefix sweep is still the instrument for "which GROUP of the file costs what"
— splitting at column-0 declarations and re-checking each prefix — and it is
NOT in the tool: for `bitops` that is 339 prefixes at 2-20 s each, where the
five groups this document's table has are worth five runs. If a worker wants it,
the shape is in this section and the constraint that makes prefixes (rather
than deletions) the right unit is in §"The measurement": a prefix is always a
valid Lean file and a deletion is not.
