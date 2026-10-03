# FORMAL_stack_floor_does_not_guard_an_acyclic_chain: a runaway recursion is a refusal on both backends, and a chain of DISTINCT functions deep enough to exhaust the stack still is not

**Area:** FORMAL (the stack-floor guard, both architectures).
**Status: OPEN by measurement, not by omission.** The guard landed
2026-10-03 (`formal/model.py`: `STACK_TRAP_STATUS`,
`STACK_FLOOR_BUDGET_BYTES`, `stack_floor_address`, `recursive_function_names`;
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py`:
`_emit_stack_floor_guard`) and it fixes the defect its predecessor doc recorded
— recursion past the fixed frame size is now `exit(2)` and not a SIGSEGV, on
both machines. What it does not cover is stated here with the measurement and
the one blocker, because the blocker is a documented design limit of the proof
side and not something a patch on the emitter side can decide.

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

## What is not fixed: a chain of DISTINCT functions

`model.recursive_function_names` emits the guard in every function that lies on
a call-graph **cycle**, and in no other. A chain of distinct functions has a
finite depth, so it is not what the guard is for; but "finite" is not "small",
and a program whose call graph is 60 frames deep and 128 KiB per frame still
walks off the end of an 8 MiB stack with no refusal.

**Measured that this is reachable, not merely arguable**: arm64 refuses at 59
recursive frames, and the emitter does not care whether the frames came from a
cycle — so a DAG sixty levels deep is the same 7.5 MiB. Whether any file in this
repository's corpus builds such a chain was NOT measured here; the number of
call-graph levels in `formal/arm64_codegen.py` (the deepest file the sweep
compiles) is the measurement to take first, and it is a `tools/formal_sweep.py`
run, which a light worker may not do.

## The blocker, and why it is not an emitter decision

The obvious repair is "emit the guard in every function". That was measured,
and it costs a proved contract per export:

* `formal/arm64_proof_gen.py::_dylib_contract_proof` returns `""` — no contract
  — for an export whose body contains **any** conditional branch, because
  `Refine.Block.step` is one function of one state and a conditional branch
  does not have one. Its own comment says so, and the enclosing emitter turns
  the empty string into a NAMED `sorry` obligation against the derived spec.
* So with the guard in every prologue, `test_formal_dylib.py`'s
  `a wrong spec is rejected, not believed` went red with exactly the message it
  exists to be able to produce: *"lean ACCEPTED a contract claiming triple
  computes a wrong multiplier — the per-export contract is not being checked
  against the machine, so it is an admitted claim wearing a proof's clothes"*,
  and the proof census went from one `sorry` in the file to one per export.
  Measured on the guard applied to every prologue, then reverted.

The cycle rule is therefore not a narrowing that happens to be safe: **every
recursive function contains a branch** (a branch-free body that calls itself
does not return, so it is not a program this backend can be asked about), so
the export contracts that exist today are exactly the straight-line,
non-recursive ones, and they are byte-identical images with the guard in place.
Widening the rule past the cycles buys no contract and loses all of them.

## The exact next step

1. **Measure first** (a sweep, so not a light worker): the maximum call-graph
   DEPTH over `formal/`, `std/` and the repo's own `.py` files, and the depth
   at which an arm64 frame chain exceeds `STACK_FLOOR_BUDGET_BYTES`. If no
   corpus file is within an order of magnitude of the budget, this document is
   a stated limit with no work behind it, and the honest thing is to say so in
   `formal/model.py`'s `recursive_function_names` — which already does.
2. **Then, only if the answer is "close"**: the fix belongs in
   `lib/Refine.lean` / `lib/Contracts.lean`, not in an emitter. A
   `Refine.Block` whose step is a two-way conditional needs either a `Block`
   per arm with a join, or a step relation that quantifies over the condition —
   and either way `Contracts.ExportBody.atExit`, which is stated at
   `image.base + image.codeSize`, has to be re-derived for a body that can leave
   through two addresses. That is a proof-side project with the `prooflib`
   build in front of it.
3. **The cheaper alternative, if 2 is too big**: a guard on the acyclic chain
   at its DEEPEST function rather than at every function — i.e. widen the rule
   from "on a cycle" to "on a cycle, or reachable from one". That is a
   one-line change to `recursive_function_names` and it is deliberately NOT
   what landed, because `helper -> deep` is the shape it would guard and
   `helper` is a perfectly ordinary function whose export contract is currently
   proved; the cost is the same cost, paid on a different set of functions.
   Measure 1 first and the choice may be free.

## Reproducing

```
$ printf 'def deep(n: Int) -> Int:\n    if n <= 0:\n        return 0\n    return deep(n - 1) + 1\n\ndef main(n: Int) -> Int:\n    return deep(5000)\n' > .tmp/deep.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/d50 .tmp/deep.mojo && .tmp/d50; echo $?
2
$ python3 fire.py build --formal --backend=x86_64 --no-prove -o .tmp/x50 .tmp/deep.mojo && arch -x86_64 .tmp/x50; echo $?
2
```

The acyclic case is the same program with `deep` renamed per level, which is
what step 1 measures; and `test_formal_run.py`'s
`stack_floor_deep_recursion_is_a_status` /
`stack_floor_mutual_recursion_is_a_status` (both architectures) plus
`check_stack_floor_decision`'s `acyclic_chain` and `out_of_image_call` probes
are the regression net for what did land.