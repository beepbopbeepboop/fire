# The arm64 proof-time floor after the step-OK swap is ONE declaration: `compiles_correctly_universal`, at 83% of the file

**Class:** performance. **Area:** `formal/arm64_proof_gen.py`'s CFG walk
terminal-value-flow and glue emission (`generate_arm64_proof`'s `step_tests`
/`compiles_correctly_universal`, and the per-path `have hpcb_/hcbz_/hs_/hg_`
chains), against `lib/ProofLib.lean`'s `arm64_go_exit` and `lib/work.lean`'s
`rec1_glue_gen` / `go_exit_step`. **arm64 only** — the x86-64 generator proves a
different thing over `lib/X86.lean` and shares none of this code.

**Status 2026-10-05 (`work/formal54-docs`): the reader the per-block
decomposition needs is FIXED and TESTED, and the decomposition's own premise is
MEASURED and does not hold. The 16 s is two giant `simp only [...]` sets, not
the walk — and per-block splitting of either of them buys nothing.** In the order
a reader needs them; the sections below are unchanged and are what these four
measurements correct or add.

* **THE COST IS TWO `simp only` SETS, AND ONE OF THEM IS A CONSTRUCT THIS
  DOCUMENT NEVER NAMED.** Measured on this tree, `bitops` arm64, one `lean` per
  variant through `formal/lean.py::run_lean`, **three repetitions each, minimum
  wall** (`tools/formal_proof_shape.py`'s `--mode profile` gives the same run):

  | variant | wall | cpu |
  |---|---:|---:|
  | the file as emitted | **20.76 s** | 29.19 s |
  | the four `hx30_{bi}` lemmas replaced by `sorry` | 14.13 s | 20.20 s |
  | the four terminal value flows replaced by `all_goals (first \| done \| sorry)` | 14.37 s | 19.57 s |
  | **both** | **4.88 s** | 10.40 s |

  So `hx30_{bi}` and the terminal value flow are **6.6 s and 6.4 s** — the same
  size each, and together 76% of the file. **§"What is actually left" item 2's
  8.3 s "in the walk" is not the walk.** The profile's own buckets put
  `refine` at **0.51 s** and `omega` at 0.17 s, and `rec1_glue_gen` is applied by
  `exact`, so the whole `rec1_glue_gen`/`go_exit_step` chain this document's item
  2 wants a `lib/work.lean` lemma for is **under a second of the 8.3**. What the
  8.3 s actually is:

  ```lean
  have hx30_4 : (bitops_b4_qS29 (({ s_2 with pc := 4294968060 }))).x30 = UInt64.ofNat 4294968180 := by
    simp only [hsid_2, hsid_0, bitops_b0_qS0, …bitops_b0_qT7,
               bitops_b2_qS0, …, bitops_b4_qS0, …, bitops_b4_qS29, …,
               bitops_b4_qT1, …, bitops_b4_qT29,
               arm64_reg, arm64_set_reg, Arm64State.init]
    simp (disch := decide) [mem_read_after_write_u64, mem_read_after_write_u64_ne,
                            mem_two_writes_same]
  ```

  one `simp only` naming **every state definition of every block on the path** —
  80 names on the widest of the four, over a 30-instruction block — and it is
  emitted at `formal/arm64_proof_gen.py:6911-6917` (`_gen_universal_e2e_cfg`'s
  `is_ret` arm), a site **no bug doc in `bugs/` names**. The terminal value flow
  is the same shape, which is why §"What is actually left" item 1's 7.8 s and
  item 2's 8.3 s came out so close: they are one construct counted twice, once
  under each name.

* **ITEM 1'S NEXT STEP — "state the terminal value flow the same way: one
  `have` per block, proved from that block's own short `simp only` list, then
  compose the blocks with `rw`" — IS THE RIGHT IDEA AND IT DOES NOT PAY, MEASURED
  BOTH WAYS.** It was worth doing as an experiment because this document is
  right that the cost is the deep chain, so the experiment was run on the
  generated file rather than argued:

  | what was changed in `bitops_proof.lean` | wall (min of 3) | cpu | checks? |
  |---|---:|---:|---|
  | nothing (the file as emitted) | 20.76 s | 29.19 s | yes |
  | **the four terminal value flows**: one `all_goals try simp only` pass per block, reverse order, each carrying only that block's `_qS/_qT` names | 22.34 s | 29.39 s | yes |
  | **the four `hx30` lemmas**: the same split, each pass ALSO carrying the shared non-block names (`hsid_*`, `arm64_reg`, `arm64_set_reg`, `Arm64State.init`) | 20.27 s | 27.97 s | yes |
  | the same split of `hx30` WITHOUT the shared names | 15.91 s | 22.65 s | **no** — 4 unsolved goals |
  | `+decide` dropped from the four terminal flows | 22.03 s (paired run) | — | yes, 1.3 s slower than its own baseline |

  **The split that checks is the split that costs nothing, and the split that
  pays does not check** — which is the whole answer, and it is the same shape as
  this document's own §"What is ruled out" finding about the `simp` set size.
  The cost is not the number of rewrite rules and not the number of `simp`
  invocations; it is **the size of the term one of them is asked to rewrite**,
  which per-block passes do not shrink because each pass still has to reduce the
  whole `{ … with mem := mem_write_u64 (mem_write_u64 … ) }` nest the block's
  chain has accumulated. Measured directly: rewriting the generated file so each
  `_qT{k}`'s `mem :=` field is deleted — a **wrong** model, so it does not
  check, and only the TIMING is read — takes the file from 26.6 s to **6.4 s**.
  The memory-write nest in the state definitions is most of what the terminal
  flow and `hx30` are rewriting, and no re-association of the same rewrites
  touches it.

  **What that leaves as the lever, stated as a measurement rather than a
  proposal**: the state definitions carry the memory history as a term, and
  anything that needs one register has to carry it. The three ways off that are
  (a) a `mem`-free projection of the state — i.e. `arm64_reg` and friends
  applied to a state whose `mem` is opaque, which is a `lib/ProofLib.lean` shape
  rather than an emitter change; (b) per-block MEMORY facts (the frame slot
  holds the return address, established once in the prologue and preserved),
  which is §"What is actually left" item 1 applied to `mem` instead of to `x0`
  and is the same kind of work; (c) accepting the 20 s and moving on. (a) and (b)
  are projects, and neither is this document's to decide.

* **`_written_expr` — the reader a per-block chain is BUILT ON — WAS BLIND TO
  EVERY REGISTER WRITE WRAPPED IN A FIELD UPDATE, AND IS FIXED.** This is the one
  defect here that was a FALSE CLAIM rather than a slow proof, and it is fixed
  with `test_formal_call_proof_gen.py::TestTheRegisterValueReaderReadsEveryWrapper`
  (three rows, one of them a Lean check). A step's result is not one shape: it
  is `some EXPR` where `EXPR` is an `arm64_set_reg` application **or** an
  `Arm64State` record update, and for every instruction that writes registers
  AND writes `sp` the register write is inside the update:

  ```lean
  some { (arm64_set_reg 30 (arm64_set_reg 29 s …) (mem_read_u64 s.mem (s.sp + 8).toNat))
         with sp := s.sp + UInt64.ofNat 16 }
  ```

  The reader matched only the top-level spelling, so it answered `None` for
  every `LDP`/`STP` with writeback — **including the `ldp x29, x30, [sp], #16`
  that is a function's epilogue** — and `_emit_reg_chain` (its one caller) reads
  `None` as "this instruction does not change the register". Measured, arm64,
  `bitops` block 4 (30 instructions), register 30: the chain concluded
  `arm64_reg 30 ST` — "x30 is untouched by this block" — while instruction 28 of
  that block is the load that writes it. Nothing in the emitter has an oracle,
  so nothing failed at emission; the false step surfaced as `unsolved goals` on
  `hT28` when the chain was put in a file and handed to Lean.

  **This is why item 1 could not simply be built**: "one `have` per block" is
  `_emit_reg_chain` per block, and per block it is wrong for exactly the block
  that ends a function. It is now right there (the same file, the same chain,
  concludes the load's own expression and checks with 0 `sorry`), and it is the
  precondition for the decomposition above — which is still worth attempting on
  a file where the measurement says it will not pay.

  Corpus reach: over all 93 `formal/examples` builds, `_emit_reg_chain` is called
  **7** times and **no** emitted step is a false "unchanged" claim either before
  or after this fix, so nothing in the corpus was wrong; the defect was latent
  and the three corpus examples whose chains pass through an `LDP` (`countdown`,
  `wdiff`, `wge`, all `LDP x0, x2`) read the same value before and after because
  their chains happen to be asked about registers the `LDP` does not write. The
  generated proofs are **byte-identical** before and after (`bitops`, arm64,
  257 326 bytes), which is the check a reader wants for a change that must not
  move a proof.

**Status: OPEN, measured, NOT FIXED for the cost; the reader the decomposition
needs is FIXED.** Filed from `work/formal24-proof-speed` immediately after
landing the step-OK derivation (commit `6b1ddbe0`), which is what produced the
attribution below. This doc is the *remainder* of that pass, not a duplicate of
it: the step-OK layer is gone (`formal/examples/bitops.mojo` 33.8 s -> ~18 s)
and this is what is left.

**Status (2026-10-04, `work/formal29-5`): the attribution below HOLDS, item 2's
stated next step does NOT, and the instrument is now in the tree.** Below, in
the order a reader needs them:

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

**BOTH ITEMS BELOW ARE CORRECTED BY THE 2026-10-05 MEASUREMENT AT THE TOP.**
Item 1's next step was measured and does not pay; item 2's 8.3 s is not the walk
and not the glue chain — it is the `hx30_{bi}` lemma, a site this document never
named. Read this section as the record of what was believed, not as the plan;
the plan is the four bullets at the top.

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
   **MEASURED 2026-10-05 AND REFUTED** — as a re-association of the same
   `simp only` rewrites, per-block passes cost 22.34 s against 20.76 s for the
   file as emitted, and the variant that DOES pay (15.91 s) does not check. The
   cost is the memory-write nest inside the state definitions, which per-block
   passes still have to reduce; the top Status section has the numbers and the
   three ways off it. **The reader this step is built on was blind to the
   epilogue's register write and is now fixed**, so the step is available and
   is not worth its cost on this file.
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
   **AND THE `lib/work.lean` ROUTE IS ALSO MEASURED AND NOT THE ANSWER.** The
   8.3 s is not this chain: `rec1_glue_gen` is applied by `exact`, and
   `--mode profile` puts `refine` at **0.51 s** and `omega` at 0.17 s for the
   whole file, so everything in this item is under 0.7 s of the 8.3. The other
   7.6 s is the `hx30_{bi}` lemma named at the top, and it is a `simp only` over
   the path's state definitions like the terminal value flow is.

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
