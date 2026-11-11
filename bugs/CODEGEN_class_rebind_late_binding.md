# CODEGEN_class_rebind_late_binding

## Summary
fire refuses to compile a class whose method reads a parameter that the enclosing function rebinds:
```
method `finish_request` of class `DualStackServerMixin` reads `args`, a parameter or local of `_main`, which declares the class, and reads `args`, which the enclosing function rebinds, so a snapshot taken at the class statement could differ from Python's late binding
```

## Source (CPython 3.15.2)
- Lib/socketserver.py (DualStackServerMixin)

## Status
Open. Python late-binds the name, so the class must see the value the enclosing function has when the method runs.

Attempt history (2026-11-11): 33 registry rounds, all superseded. Round 31 (19 commits, ~1,475 lines across
`mojo/backend_gimple/` and `mojo/middle/`) is on master, merged as `67083801e` (via `77cd9afae`). Its own 19
reported failures in `test_gimple_runner.py` are not yet verified on master. The registry entries and branches for
the rounds have been removed; this doc is the only record. Nothing is left to start from.

Landed 2026-11-11 (partial fix): the repro now COMPILES instead of being refused. Its runtime answer is checked by
`test_class_rebind_late_binding.py` (2026-11-11): it FAILS on the tree before round 31 with the original refusal,
and PASSES on master, printing `2`. The `fire.py build` path still aborts at load for every program
(`CODEGEN_peekable_iterator_methods_not_emitted`), which this test does not exercise (it runs through the gimple harness).
The `stdlib-syntax` red (six files, `CODEGEN_simd_math_call_violated_constraint`) is pre-existing on master and unchanged.

## Done when
`python3 test_class_rebind_late_binding.py` passes: it compiles the late-binding program and prints `2` (CPython's
answer). That is now true on master. Open question for the owner: the doc also asked for the stdlib compile to be green.
That red is pre-existing and filed separately, so it is not this bug's. If you agree, delete this doc in a commit that
says so; until then it stays open.
