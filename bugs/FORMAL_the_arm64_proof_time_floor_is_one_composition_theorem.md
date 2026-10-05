# The arm64 proof-time floor after the step-OK swap is ONE declaration: `compiles_correctly_universal`, at 83% of the file

**Class:** performance. **Area:** `formal/arm64_proof_gen.py`'s CFG walk
terminal-value-flow and glue emission (`generate_arm64_proof`'s `step_tests`
/`compiles_correctly_universal`, and the per-path `have hpcb_/hcbz_/hs_/hg_`
chains), against `lib/ProofLib.lean`'s `arm64_go_exit` and `lib/work.lean`'s
`rec1_glue_gen` / `go_exit_step`. **arm64 only** — the x86-64 generator proves a
different thing over `lib/X86.lean` and shares none of this code.

**Status: OPEN, measured, NOT FIXED.** Filed from `work/formal24-proof-speed`
immediately after landing the step-OK derivation (commit `6b1ddbe0`), which is
what produced the attribution below. This doc is the *remainder* of that pass,
not a duplicate of it: the step-OK layer is gone (`formal/examples/bitops.mojo`
33.8 s -> ~18 s) and this is what is left.

**Re-measured 2026-10-05 (`work/formal31-5`), two runs, and THE FLOOR IS
UNCHANGED: 20.5 s / 20.1 s wall, 29.3 s / 28.7 s CPU, peak RSS 2.0 GB, `rc=0`,
no warnings, on `master` at `7ac78995`.** The table below was measured on the
`formal24-proof-speed` tree, so this is the statement that it still describes
today's emitter: nothing in the five weeks since moved the number, and the
attribution (83% in one declaration) is the thing a fix has to beat, not the
total.

**And the re-measurement found a TRAP that would have produced a fake timing,
which is why it is written down at all: `fire.py build --formal` on an unchanged
tree prints `Proof: … (verified from cache)` and runs NO Lean at all** — the
verdict is content-addressed on the proof bytes, `lib/*.olean` and the
toolchain, so the whole command takes ~1.1 s and its cost is not a proof time.
Any timing taken from a `fire.py build --formal` line is a timing of the cache.
The bytes have to change (or the check has to be made directly, as §"How to
re-derive" now spells it) before Lean runs.

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
   direction: the per-path `h_adv_{bi}_{k}` fuel-arithmetic rewrites
   (`show 30 + (200000 + 48 * n.toNat - 48) = … from by omega`, repeated at
   every step of every path) are a per-step re-derivation of one monotone
   fuel identity, and hoisting them into one lemma per path is mechanical.

**Do NOT start from "raise the ceiling".** `PROOF_WALL_S`/`PROOF_CPU_S` are
1500 s and nothing in the 49-example corpus comes near them; the file that hurts
is the biggest *generated* proof, and the fix for that is a smaller generated
proof. The one row where size did not predict cost (`formal/lean.py`'s module
docstring: `wide_recv` 703 KB in 93 s, `udivmod` 437 KB in 298 s before this
pass) is `udivmod`, which this pass took 52.9 s -> 29.6 s — so the ranking
itself moved, and a bound re-derived from the old one would be re-derived from
stale data.

## How to re-derive the table

**Every command below was run on 2026-10-05 and is one a reader can paste. The
first version of this section named `.tmp/genproof.py`, which was scratch on the
`formal24-proof-speed` tree and does not exist here — and `.tmp/` is
git-ignored, so nothing in the repository regenerates it. That is why the
generation step is `fire.py build --formal --no-prove`, which writes the same
`.lean` next to the image.**

```sh
export PATH=/opt/homebrew/bin:$PATH

# 1. the library, if it is not current (one build, exclusive, ~27 MB of .olean)
python3 tools/memslot.py --gb 12 --label prooflib -- python3 -c "
import os,sys; sys.path.insert(0,os.getcwd())
from formal.lean import find_lean, ensure_library
ensure_library(find_lean(os.getcwd()), os.path.join(os.getcwd(),'lib'))"

# 2. GENERATE the proof without checking it.  --no-prove is the whole point:
#    without it this step may print "(verified from cache)" and check nothing.
python3 tools/memslot.py --gb 8 --label gen -- python3 fire.py build --formal \
    --no-prove --backend=arm64 -o .tmp/out/bitops formal/examples/bitops.mojo
#    -> .tmp/out/bitops_proof.lean

# 3. TIME a real check of those bytes.  This is `formal/lean.py::run_lean` and
#    nothing else — never launch `lean` by hand; the guard is what bounds it.
#    Copy the file first: `fire.py` writes it read-only.
cp .tmp/out/bitops_proof.lean .tmp/z/proof.lean && chmod u+w .tmp/z/proof.lean
python3 tools/memslot.py --gb 8 --label leanchk -- python3 -c "
import os, sys
sys.path.insert(0, os.getcwd())
from formal.lean import find_lean, run_lean
R = os.getcwd()
lean = find_lean(R)
env = dict(os.environ, LEAN_PATH='%s:%s' % (R, os.path.join(R, 'lib')))
r = run_lean(lean, [sys.argv[1]], env=env)
print('rc=%s exceeded=%r wall=%.1fs cpu=%.1fs peak_rss=%s'
      % (r.returncode, r.exceeded, r.wall_s, r.cpu_s, r.peak_rss))
print((r.stdout or '')[:300], (r.stderr or '')[:300])
" .tmp/z/proof.lean
```

Measured on this tree, step 3 twice: `rc=0 exceeded=None wall=20.5s cpu=29.3s
peak_rss=2132197376` and `wall=20.1s cpu=28.7s peak_rss=2129297408`. **The
`--root=` flag is NOT what step 3 passes and must not be added**: the proof
imports `ProofLib` and `work`, and what resolves them is `LEAN_PATH`, which is
the same two-directory string `formal/x86_64_endtoend_test.py::_run_lean` builds.

**The prefix sweep — the instrument the attribution actually comes from — is
still scratch and is still not committed**: split the generated file at its
column-0 declarations, write each prefix, and check each one through step 3's
`run_lean`. A prefix is always a valid Lean file, which a "delete this group"
variant is not — the file stops elaborating and the timing then measures Lean's
error recovery.