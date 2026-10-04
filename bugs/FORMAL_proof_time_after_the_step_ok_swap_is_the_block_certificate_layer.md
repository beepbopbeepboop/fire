# The arm64 proof-time floor after the step-OK swap is the block-certificate layer: 85% of a generated proof, in `simp only` over the per-instruction state functions

**Class:** performance. **Area:** `formal/arm64_proof_gen.py`'s CFG block
certificates (`_gen_block_lemmas` and the `{stem}_b{k}_qS{i}` / `_qT{i}` state
functions they rewrite through), against `lib/ProofLib.lean`'s `arm64_runs` and
`lib/work.lean`'s `work_body_run` / `work_body_mid`. **arm64 only** — the
x86-64 generator proves a different thing over `lib/X86.lean` and shares none of
this code.

**Status: OPEN, measured, NOT FIXED.** Filed from `work/formal24-proof-speed`
immediately after landing the step-OK derivation (commit `6b1ddbe0`), which is
what produced the attribution below. This doc is the *remainder* of that pass,
not a duplicate of it: the step-OK layer is gone (33.8 s -> 18 s on
`formal/examples/bitops.mojo`) and this is what is left.

## The measurement

`formal/examples/bitops.mojo`, arm64, one `lean` per file, medians of one run
through `formal/lean.py::run_lean` on a machine running 8-16 other formal
workers (so the wall figures carry several seconds of noise and the CPU figures
are the ones to read). The instrument is a PREFIX sweep: the generated file is
split at its column-0 declarations and each prefix re-checked, so the delta
between two prefixes is that group's own cost. A prefix is always a valid Lean
file, which a "delete this group" variant is not — the file stops elaborating
and the timing then measures Lean's error recovery.

| prefix ends after | wall | CPU | delta |
|---|---|---|---|
| `*_runs_*`, `*_insn_*` | 0.8 s | — | — |
| all 53 `*_sr_*` (step RESULT) | 1.6 s | — | **0.8 s** for 53 lemmas |
| all 53 `*_step_ok_*` (step OK) | 2.9 s | 5.8 s | **1.3 s** for 53 lemmas |
| `*_compiles_correctly`, the `qS`/`qT` defs | 2.9 s | 5.2 s | ~0 s |
| **the whole file** | **19.5 s** | **28.0 s** | **16.6 s (85%)** |

The 16.6 s is the block-certificate layer: 51 `{stem}_b{k}_{selfN,runs,mid}`
lemmas plus `bitops_compiles_correctly_universal`, whose proofs are chains of

    simp only [b0_qS0, b0_qT0, b0_qS1, ... 60 names ..., arm64_set_reg]

— one per block state, over the ~92 `def {stem}_b{k}_qS{i} / _qT{i}`
state functions. `lean --profile` on the same file agrees on the shape and names
the buckets (`blocked (unaccounted) 104s`, `simp 8.48s`, `type checking 8.24s`,
`tactic execution 4.17s`; `import` is 0.64 s, so the library is not the cost).

**Two things this rules out, measured rather than assumed**, because both were
the obvious next suspects:

* **The remaining `native_decide` calls are not the cost.** Rewriting all 53
  `have hinsn : arm64_read_insn <stem>_code <pc> = (<word> : UInt32) :=
  by native_decide` into the `{stem}_insn_{i}` lemma that already states
  exactly that (by `rfl`) changes nothing: 18.1 s -> 17.9 s wall, 26.9 s ->
  26.8 s CPU, i.e. inside the noise. Likewise `decide` in place of
  `native_decide` on the 262 remaining closed-`UInt32` numeral facts is
  18.4 s -> 17.9 s wall and 26.3 s -> 23.0 s CPU — about 3% of CPU, not worth a
  second change on its own. `native_decide`'s per-call cost is amortised across
  the file by the elaborator's LCNF pass, so the count of calls is not the
  count of the cost.
* **Extending `lib/work.lean`'s `work_step_*` family is not the cost either.**
  247 of the corpus's 2 230 step-RESULT lemmas still take the discriminator
  route (`_step_facts`: 56 `native_decide`, `unfold arm64_step`, two `simp`
  passes) because step-table entries 14-17 and 36-53 have no `work_step_*`
  lemma. Replacing all of `bitops`'s three such lemmas with `by sorry` saves
  **0.5 s of 19.7 s**. Across the corpus that route is ~247 x 0.17 s = ~42 s
  over 49 files, under 1 s per file — and it would cost a `lib/*.lean` change,
  which invalidates every worker's `.olean` cache for a second-order win.

## What is actually left, and the next step

`{stem}_b{k}_qS{i}` / `_qT{i}` are `def`s, and the block lemmas rewrite through
them with an explicit `simp only [...]` list rather than by `unfold`. Two costs
follow, and they are separable:

1. **Per-call `simp` set construction.** `simp only [a, b, c, …, 60 names]`
   builds a `DiscrTree` over 60 rewrite rules on every call, and a block
   certificate makes one call per state. A `def`-per-state chain that is only
   ever *delta-reduced* wants `unfold`, which is a `whnf` loop with no
   discrimination tree at all.
2. **Per-state name lists.** The same 60-name list is re-spelled in every
   lemma of every block, so the file is 2 464 lines of block lemmas (63% of its
   3 939 lines) of which the *names* are most of the bytes, and every edit to
   the state-function set has to be replayed at ~30 sites.

**Next step, in order:** measure (1) alone on one block certificate — replace
one `simp only [qS…, qT…, arm64_set_reg]` with `unfold qS… qT…` followed by the
existing `try` closers, and see whether it still closes. If it does, the state
functions become `unfold` targets and the block layer loses its `simp` set
construction entirely. Only after that is worth looking at (2): a single named
`simp only` set per block (`@[simp] attribute` on the `qS`/`qT` defs, or one
generated `section` with a shared lemma bundle) replaces 30 spellings with one.

**Do NOT start from "raise the ceiling".** `PROOF_WALL_S`/`PROOF_CPU_S` are
1500 s and nothing in the 49-example corpus comes near them; the file that hurts
is the biggest *generated* proof, and the fix for that is a smaller generated
proof. The one row where size did not predict cost (`formal/lean.py`'s module
docstring: `wide_recv` 703 KB in 93 s, `udivmod` 437 KB in 298 s before this
pass) is `udivmod`, which this pass took 52.9 s -> 29.6 s — so the ranking
itself moved and a bound re-derived from the old one would be re-derived from
stale data.

## How to re-derive the table

    python3 tools/memslot.py --gb 12 --label prooflib -- python3 -c "
    import os,sys; sys.path.insert(0,os.getcwd())
    from formal.lean import find_lean, ensure_library
    ensure_library(find_lean(os.getcwd()), os.path.join(os.getcwd(),'lib'))"

    # one proof, no Lean check during generation
    python3 tools/memslot.py --gb 8 --label gen -- python3 .tmp/genproof.py \
        formal/examples/bitops.mojo arm64 .tmp/out/bitops

    # then the prefix sweep: split the generated file at its column-0
    # declarations, write each prefix, and check each one through
    # formal/lean.py::run_lean.  Never launch lean by hand.