# FORMAL_stack_floor_does_not_guard_an_acyclic_chain: a runaway recursion is a refusal on both backends, and so is a chain of DISTINCT functions

**Area:** FORMAL (the stack-floor guard, both architectures).
**Status: MEASURED and WIDENED, 2026-10-03 (`work/formal13-6`).** The guard
landed 2026-10-03 (`formal/model.py`: `STACK_TRAP_STATUS`,
`STACK_FLOOR_BUDGET_BYTES`, `stack_floor_address`,
`stack_floor_guarded_names`; `formal/arm64_codegen.py` and
`formal/x86_64_codegen.py`: `_emit_stack_floor_guard`) and it fixed the defect its
predecessor doc recorded — recursion past the fixed frame size is `exit(2)` and
not a SIGSEGV, on both machines. The cycle-only rule left the acyclic chain open,
and §"The measurement" below is the number that decided it: **the deepest single
image in this corpus is 76 frames against the 60 an arm64 budget affords.** So
the guard is now emitted on a call-graph cycle **OR** in every body that already
contains a conditional branch, which is free — a body that already branches had
no per-export contract to lose — and leaves a residual of **7 frames, median 3**,
which is the chain of bodies with no branch at all and which only
`lib/Refine.lean` can close.

## What is fixed, and what it cost

```
arm64    deep(59) exit 0    deep(60) exit 2    was: 61 then SIGSEGV (exit 139)
x86-64   deep(471) exit 0   deep(472) exit 2   was: ~450 then SIGSEGV
```

The two lost arm64 frames are the trade `STACK_FLOOR_BUDGET_BYTES` states in
its own comment: the budget is 7.5 MiB, the measured usable stack below the
startup stub's SP is between 7.63 and 7.75 MiB, and being under it costs one to
two 128 KiB frames. A budget that OVERestimates the real stack leaves the guard
silent and the program dies as it did before — no worse than the defect — while
one that underestimates costs depth, which is a refusal and never a crash. That
asymmetry is the reason the number is a named policy constant and not a literal
in two emitters.

## The measurement, and it decided the rule

`model.call_graph_depth` (new, with `model.call_graph_edges` factored out of the
old `recursive_function_names` so the rule and the measurement walk ONE graph)
and `tools/formal_call_depth_census.py` (new — parse plus one graph per file,
680 files, no sweep and no build). Over this repository and the stdlib:

```
deepest image: 76 frames
  arm64  traps at  60 frames; deepest measured is 76 = 1.3x the budget
  x86-64 traps at 480 frames; deepest measured is 76 = 0.2x the budget
deepest chain the guard does NOT reach (bodies with no branch, no cycle): 7
76    202   1400   4   formal/arm64_codegen.py   <-- AT/OVER the arm64 budget
69    188   1195   4   formal/x86_64_codegen.py <-- AT/OVER the arm64 budget
44    195    694   3   fire_compiler.py
...
repository   413 images; median depth 3, p90 6, max 76
stdlib       181 images; median depth 3, p90 7, max 16
```

**The answer to the question this document spent three revisions asking is
"close" — the corpus is ALREADY INSIDE the hole, by 1.3x — and the two deepest
images are the two this backend's own codegen lives in**, which is the file this
document already named as the one to measure first. The median is 3 and the p90
is 6, so the risk is concentrated in exactly two files and is not a general
property of the corpus; the depth is also an upper bound twice over (`iter`'s
edges are a superset of the calls the emitter makes, and `call_graph_depth`
bounds the longest simple path by the condensation), so the real figure is at
most 76 and at least 60 — either way the same order as the budget.

**The x86-64 figure is why the rule had to be widened rather than the budget
raised.** 76 frames is 0.2x x86-64's budget and 1.3x arm64's, so a budget change
would fix one machine by making the other's guard fire earlier for no reason.

## The rule that landed

```python
model.stack_floor_guarded_names(functions, structs)
    = {f.name for f in functions
       if on_a_call_graph_cycle(f) or body_has_conditional_branch(f)}
```

**The second clause is free, and the argument is about the per-export contract
proof, not about code size.** `arm64_proof_gen._dylib_contract_proof` returns
`""` — no contract — for an export whose body contains ANY conditional branch,
because `Refine.Block.step` is one function of one state and a conditional branch
does not have one. So a body that already branches has no contract to lose, and a
body that does not is left exactly as it was. "Every function" would trade
proved contracts for nothing, which is what this document's predecessor
measured; "every function that already has a branch" does not.

**Which makes the predicate's DIRECTION load-bearing rather than tidy**, because
the same argument read backwards says a predicate that over-counts would take a
contract away from an export that has one. `body_has_conditional_branch` counts
only constructs that ALWAYS lower to a conditional branch on both backends with
no purity gate in front of them — `if`, `while`, `for`, `assert`, `try`, `match`,
a comprehension with a condition — and deliberately does NOT count a **ternary**
or a **short-circuit chain**, because both backends have a BRANCHLESS lowering
chosen by a purity predicate (`a if c else b` becomes a CSEL on arm64; the
branchless `and`/`or` form is gated on the left operand needing no conversion).
It also does not descend into a nested `def`, whose branch is in the nested
function's own prologue; `formal/build.py`'s `_flatten_closures` lifts every
nested def to top level before the function table exists, so this is defensive,
and `iter_nodes` would not have been.

Verified on both architectures, measured before and after, on the shape the
measurement says is reachable:

| program | before | after |
|---|---|---|
| 600 distinct functions, each calling the next, each with an `if` — arm64 | **SIGSEGV, exit 139** | `exit(2)` |
| the same program on x86-64 | **SIGSEGV, exit 139** | `exit(2)` |

600 rather than 61 because x86-64's frame is 16 KiB to arm64's 128 KiB, so its
budget affords 480 frames and a 61-deep chain is correctly INSIDE it — a single
depth cannot show the defect on both machines, and a case that fires on one is a
case about the frame size rather than about the guard.
`test_formal_run.py`'s `both_arch_an_acyclic_chain_past_the_floor_is_a_status`,
with `guard_a_straight_line_chain_is_left_alone` beside it as the negative.

**What it costs, measured rather than argued:** `test_formal_run.py` PASS=806
FAIL=0 (782 before this pair of changes, +15 stack-floor probes, +7 guard
probes, +2 generated cases). `test_formal_dylib.py` PASS=19 FAIL=0 with Lean
actually running — 1 m 5 s at 3.1 GB peak, so the CAS verdicts were a cache MISS
on the new proof bytes rather than a replay, which is the measurement that says
"no export lost a contract".

## What is still not fixed, and it is the proof side

A chain of bodies with **no** branch at all is still unguarded, and the corpus
says that chain is at most **7 frames** deep (median 3) against arm64's 60 — so
it is a bounded residual rather than an open hole, and 600 straight-line
functions in a chain still walk off the end of the stack. That is stated by
`test_formal_run.py`'s `guard_a_straight_line_chain_is_left_alone` rather than
papered over.

Closing it is not an emitter decision:

* `formal/arm64_proof_gen.py::_dylib_contract_proof` returns `""` for an export
  whose body contains ANY conditional branch, and the guard's own `cbnz`/`b.hs`
  is one. Its comment says so, and the enclosing emitter turns the empty string
  into a NAMED `sorry` obligation against the derived spec.
* So with the guard in EVERY prologue, `test_formal_dylib.py`'s
  `a wrong spec is rejected, not believed` went red with exactly the message it
  exists to be able to produce: *"lean ACCEPTED a contract claiming triple
  computes a wrong multiplier — the per-export contract is not being checked
  against the machine, so it is an admitted claim wearing a proof's clothes"*,
  and the proof census went from one `sorry` in the file to one per export.
  Measured on the guard applied to every prologue, then reverted.
* **The fix belongs in `lib/Refine.lean` / `lib/Contracts.lean`**: a
  `Refine.Block` whose step is a two-way conditional needs either a `Block` per
  arm with a join, or a step relation that quantifies over the condition — and
  either way `Contracts.ExportBody.atExit`, which is stated at
  `image.base + image.codeSize`, has to be re-derived for a body that can leave
  through two addresses. That is a proof-side project with the `prooflib` build
  in front of it, and the two `lib/*.lean` files carry `sorry`s at `InImage` and
  `Semantics` today (see the note at the bottom of
  `bugs/FORMAL_string_value_model.md`).

The cheaper third option this document used to offer — "on a cycle, or reachable
from one" — is **dominated** by what landed and is not worth taking: a DAG with
no cycle in it has no member reachable from one, so it would guard nothing that
the cycle rule did not already guard, and the measured offender
(`formal/arm64_codegen.py`, 76 frames) is a DAG.

## Reproducing

```
$ printf 'def deep(n: Int) -> Int:\n    if n <= 0:\n        return 0\n    return deep(n - 1) + 1\n\ndef main(n: Int) -> Int:\n    return deep(5000)\n' > .tmp/deep.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/d50 .tmp/deep.mojo && .tmp/d50; echo $?
2
$ python3 fire.py build --formal --backend=x86_64 --no-prove -o .tmp/x50 .tmp/deep.mojo && arch -x86_64 .tmp/x50; echo $?
2
$ python3 tools/formal_call_depth_census.py            # the measurement above
```

`test_formal_run.py`'s `stack_floor_deep_recursion_is_a_status` /
`stack_floor_mutual_recursion_is_a_status` / `both_arch_an_acyclic_chain_past_the_floor_is_a_status`
(both architectures) plus `check_stack_floor_decision`'s seven guarded-set probes
and eight `call_graph_depth` probes are the regression net for what landed.
