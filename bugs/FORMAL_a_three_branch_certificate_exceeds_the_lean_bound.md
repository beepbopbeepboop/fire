# FORMAL_a_three_branch_certificate_exceeds_the_lean_bound: two conditional
# branches prove, three do not, and it is not the instruction

**Status: OPEN, measured on arm64, 2026-10-03, and NOT a bit-test problem.**
Found while landing the bit-test proof arm
(`bugs/FORMAL_arm64_bit_test_branch_is_not_provable.md`, deleted with it): the
arm64 whole-program certificate for a function with THREE conditional branches
does not finish inside `formal/lean.py`'s 1500 s wall bound, and the control
experiment says the instruction is irrelevant.

## The measurement

Four programs, each one `if` per branch over a single parameter, built with
`fire.py build --formal` (arm64, so the proof is generated AND checked):

| program | branches | verdict |
|---|---|---|
| `x = 0; if n & 8: x += 1; return x` | 1 (TBZ) | proved, 0 `sorry` |
| `x = 0; if not (n & 4): x += 2; return x` | 1 (TBNZ) | proved, 0 `sorry` |
| `if 16 & n: …` | 1 (TBZ, mask commuted) | proved, 0 `sorry` |
| the doc's `bittest` — `n & 8`, `not (n & 4)`, `16 & n` | 3 | **`lean exceeded 1500s wall`** |
| **control:** the same three as ORDINARY COMPARISONS — `n > 8`, `not (n < 4)`, `16 < n` | 3 | **`lean exceeded 1500s wall`** |
| two of the three (`n & 8`, `not (n & 4)`) | 2 | proved, 0 `sorry` |

```console
$ python3 tools/memslot.py --gb 24 --label lean -- python3 fire.py build \
      --formal -o .tmp/three.out --backend=arm64 .tmp/three.mojo
build: proof check failed: lean exceeded 1500s wall (limit 1500s) — killed,
and this is NOT a verdict on the proof
```

The control is the whole of what makes this a separate bug: three branches of
`B.cond` cost exactly what three branches of `TBZ` cost, so nothing about the
bit test is being paid for twice. What is being paid for is
`_gen_run_cert`'s composed-state walk over one more pair of blocks.

## Why it is a bug and not a bound

`formal/lean.py::PROOF_WALL_S` is 1500 s and it exists to stop a runaway, and a
machine that cannot afford it is a legitimate answer — `MEMLIMIT_GB` and the
per-class ceilings are how this project says so. But:

* **the step is CHEAP to state and the bound is where the cost is.** The 49
  examples in `formal/examples/` are all under the bound except the ones this
  doc is about, and the per-instruction sweep over them is 1.8 s in total
  (`CLAUDE.md`). The whole-program certificate is the only part that does not
  scale.
* **the growth is in BLOCKS, not in instructions.** The three-branch program is
  24 instructions; `bugs/FORMAL_csel_in_the_model_costs_a_ternary_export_its_
  whole_proof.md` measured a 24-instruction export failing the same way with
  `CSEL` in the model. Two independent shapes, the same wall, and that doc's
  `hx30` composition is the same walk.
* **the failure is a BUILD FAILURE, not a named obligation.** `runProg` gets
  `some s` only for the paths the certificate enumerates, so the honest
  alternative to proving it is refusing the shape — and today a program that
  proves at two branches stops building at three with a message about a wall
  clock.

## The exact next step

Not a bigger bound. In this order, because each is cheaper than the one after it
and each is measurable without a full gate:

1. **Measure where the certificate spends its time.** `_gen_run_cert` emits one
   `have` per block edge and one composed `qT` chain per block; the emitted
   `bittest_blk_9_cert` / `hx30` goals are where a `set_option trace.profiler`
   would point. The question is whether it is kernel type-checking time (memory,
   which is what the doc above saw) or heartbeat time in one tactic.
2. **If it is memory**, the fix is in `lib/Refine.lean`'s composed-state lemma:
   the `qT` chain for block N is re-proved inside block N+1's certificate, so a
   chain of k blocks elaborates the same terms k times. A `qT`-composition lemma
   that takes the previous block's certificate as a hypothesis would make the
   cost linear in the number of EDGES rather than quadratic in blocks.
3. **If it is heartbeats in one tactic**, the block certs are already separate
   `theorem`s (`bittest_blk_7_cert` and so on), so the win is to stop
   `exact`-ing each block's `_runs` lemma through an `intro st hpc` that
   re-unfolds `runProg`.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ printf 'def f(n):\n    x = 0\n    if n & 8:\n        x = x + 1\n    if not (n & 4):\n        x = x + 2\n    if 16 & n:\n        x = x + 4\n    return x\n' > .tmp/three.mojo
$ python3 tools/memslot.py --gb 24 --label lean -- python3 fire.py build --formal \
      -o .tmp/three.out --backend=arm64 .tmp/three.mojo          # exceeds 1500 s
$ printf 'def f(n):\n    x = 0\n    if n > 8:\n        x = x + 1\n    if not (n < 4):\n        x = x + 2\n    if 16 < n:\n        x = x + 4\n    return x\n' > .tmp/three_cmp.mojo
$ python3 tools/memslot.py --gb 24 --label lean -- python3 fire.py build --formal \
      -o .tmp/three_cmp.out --backend=arm64 .tmp/three_cmp.mojo  # the same
```

(The comparison control reaches the same wall by a DIFFERENT route on the way
there: `if not (n < 4):` crashed the generator with
`AttributeError: 'NoneType' object has no attribute 'get'` out of
`types.infer_expr` until `_expr_bool_go` learned to thread `vtypes` — fixed in
the same commit as the bit-test arm, because a nested comparison behind a `not`
is what the control program is made of.)
