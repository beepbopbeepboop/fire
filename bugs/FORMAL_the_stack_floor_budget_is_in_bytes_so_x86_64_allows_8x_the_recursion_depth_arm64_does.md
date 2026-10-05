# FORMAL_the_stack_floor_budget_is_in_BYTES_so_x86_64_allows_8x_the_recursion_depth_arm64_does

**Area:** FORMAL — the stack-floor guard: one byte budget, two frame sizes
(`formal/model.py::STACK_FLOOR_BUDGET_BYTES`, both emitters'
`_emit_stack_floor_guard`, `formal/model.py::call_graph_depth`).

**NOT MINE.** Filed by `work/formal33-metamorphic-r2`, whose claim is
`project33:metamorphic`. This is the recursion-depth area: `project33:recursion-stack`
is a live claim, and `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`
(claimed by `formal25-5-r2`) is the doc that owns the guard and the budget. Recorded
here rather than acted on because the owner is a better place for it than this
branch is — and because the number below is worth having measured in a second place.

## What was run

Both backends, `fire.py build --formal --no-prove`, one self-recursive function and
the build's default input, through `tools/formal_fuzz.py`'s shared harness — the
same `run_on` `tools/formal_metamorph.py` uses, so `verdict` here is the same word:

    python3 - <<'PY'
    import sys, tempfile; sys.path.insert(0, "tools"); sys.path.insert(0, ".")
    import formal_fuzz as F
    tmp = tempfile.mkdtemp(dir=".tmp")
    prog = ("def down(n):\n    if n == 0:\n        return 0\n    return down(n - 1)\n"
            "def main() -> Int:\n    print(down(%d))\n    return 0\n")
    for n in (50, 59, 250, 400, 500):
        for b in ("arm64", "x86_64"):
            print(n, b, F.run_on(b, prog % n, tmp, f"{n}{b}")["verdict"])
    PY

## What was seen

The exact edges, by bisection over `n`:

| backend | deepest self-recursion that answers | first depth that traps | how |
|---|---|---|---|
| **arm64** | **58** | **59** | `exit 2` (`verdict: trapped`, rc 2) |
| **x86_64** | **470** | **471** | `exit 2` (`verdict: trapped`, rc 2) |

So for every depth in **59 … 470** the same program answers `0` on x86-64 and
exits `2` on arm64. Both are the guard working as written — `exit(2)`, not a
SIGSEGV, which is what the sibling doc records as fixed.

## Why, and it is not a mystery

The budget is **bytes** and it is **one constant for both architectures**:

    formal/model.py:36024   STACK_FLOOR_BUDGET_BYTES = 7 * 1024 * 1024 + 512 * 1024

and the frame sizes are not:

| | frame | `7.5 MiB // frame` | measured edge |
|---|---|---|---|
| arm64 | 128 KiB | 60 | **59** |
| x86-64 | 16 KiB | 480 | **471** |

The arm64 figure is the one the tree already states —
`formal/model.py::call_graph_depth` says "Every formal frame is at least 128 KiB, so
the depth that matters is `STACK_FLOOR_BUDGET_BYTES // 128 KiB` — 59 on arm64,
measured, not estimated", and 59 is exactly what this measurement found. The x86-64
figure is 8.1x it, and the ratio is the frame ratio: 128 KiB to 16 KiB, the pair the
sibling doc's frame census tabulates ("`formal/arm64_codegen.py` 76 frames / 202
bytes … `formal/x86_64_codegen.py` 69 frames / 188 bytes", with the trade spelled out
as "600 rather than 61 because x86-64's frame is 16 KiB to arm64's 128 KiB").

**So the guard is arithmetically correct and the policy is the asymmetry.** Two
consequences that are not the guard's to fix and are the reason this is filed:

* `formal/model.py::call_graph_depth`'s "**Every** formal frame is at least 128 KiB"
  is an arm64 fact stated without its architecture. On x86-64 it is 16 KiB and the
  depth is 471. Any bound derived from that sentence is 8x conservative on one
  machine, which is the safe direction but is not a fact about x86-64.
* the two architectures are **not one language implementation** over that band, and
  every harness here says so in its own vocabulary: `tools/formal_fuzz.py::classify`
  counts `trapped` apart, and `tools/formal_metamorph.py` reports `TWIN-DIVERGES-<arch>`
  when one machine answers and the other refuses. A metamorphic pair over
  `formal/examples/count.mojo` — 58 frames at the driver's argument table, 0 at
  `EXAMPLE_ARGS[0]` — sits just below the arm64 edge, and `fib`/`fact`/`sum` are one
  argument away from crossing it. Any corpus that measures recursion depth on both
  machines is measuring the budget, not the compiler.

Also measured, same host and harness, same day: a chain of 120 DISTINCT functions
each calling the next traps on arm64 at every input tried (50, 59, 60, 61, 70, 100,
200, 250) and answers on x86-64 at all of them — the same asymmetry from the
frame-size side.

## What was expected

Not a particular number. The sibling doc is explicit that the budget is a trade and
that a change "would raise raised**" — the budget is 7.5 MiB against a much larger
default stack, chosen so a runaway recursion is a refusal rather than a SIGSEGV.
What was not expected is that the two edges for ONE shape are 58 and 470 rather than
the ~60 and ~70 the sibling doc's per-function census suggests.

## The exact next step

One of these, and the choice is the owner's:

1. **Make the budget a DEPTH on each architecture** — `BUDGET // frame_size` with the
   frame size taken per emitter, so both machines refuse at the same `n`. Cost:
   the byte guarantee is gone, and the guard is then a *depth* claim rather than a
   *stack* claim, which is a different theorem for the proof side to discharge
   (`formal/arm64_proof_gen.py`, `formal/x86_64_proof_gen.py`).
2. **Raise arm64's frame budget to match x86-64's depth** — `STACK_FLOOR_BUDGET_BYTES`
   to 60 MiB for arm64 only. Cost: 8x the stack a runaway recursion may spend before
   it is refused, which is the thing the guard was sized to bound.
3. **State the asymmetry and make the harnesses own it** — one line in
   `formal/model.py`'s budget docstring and in `tools/formal_fuzz.py::classify`
   saying the recursion bound is per-architecture, so `TWIN-DIVERGES` on a `trapped`
   pair is a KNOWN thing rather than a finding to be re-derived every sweep.

This branch did not choose, because every file named above is in another round's
claim, and it filed this instead.