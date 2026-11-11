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

Attempt history (2026-11-11): 33 registry rounds, all superseded. The newest one holds the work:
`work/bug-codegen-class-rebind-late-binding-r31` (19 commits not on master, ~1,475 lines across
`mojo/backend_gimple/` and `mojo/middle/`). Its own test run reported 19 failures it called pre-existing, and
the landing gate went red on `stdlib-syntax` (`std/random/philox.mojo`, `test/math/*`) with that branch in the
batch. The next worker starts from that branch (the planner does this), reads `git diff master...HEAD` first,
and must make the stdlib compile green before the branch can land.

Landed 2026-11-11 (partial fix): round 31's compiler change is on master. The doc's repro now COMPILES
instead of being refused; it does not yet run correctly, because every compiled program currently aborts at load
(`CODEGEN_peekable_iterator_methods_not_emitted`). Still open: the Done-when test below, and the runtime answer `2`.
The `stdlib-syntax` red (six files, `CODEGEN_simd_math_call_violated_constraint`) is pre-existing on master and unchanged.

## Done when
A quick regression test `test_class_rebind_late_binding.py` (to be written; the branch's cases are inside the
slow `test_gimple_runner.py`, so they are not the quick test) compiles and runs:
```
def outer(args):
    class C:
        def m(self):
            return args
    args = 2
    return C().m()
print(outer(1))
```
and requires output `2` (CPython's answer). It passes on the branch, and the stdlib compile is green. Then this
doc is deleted in the same commit.
