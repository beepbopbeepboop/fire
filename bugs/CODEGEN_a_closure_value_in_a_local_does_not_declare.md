# CODEGEN: a closure value stored in a module-scope local is never declared, so the file does not compile

Found 2026-10-02 while fixing defect 2 of
`bugs/COMPILE_FAIL_decorator_application_dropped.md` — that entry's plan did
not account for this, and the fix it names is not exercised for the closure
spelling because the closure spelling does not compile at all on this tree.

## What was run

    $ python3 tools/memslot.py --gb 8 --label dcv -- python3 .tmp/w/g.py deco2.py
    COMPILE FAIL: gcc -fgimple compilation failed: .../tmp1sdjtnqz.c: In function '_toplevel':
    .../tmp1sdjtnqz.c:8:36: error: 'f' undeclared (first use in this function)
        8 | #include <stdio.h>
          |                                    ^

The fixture, which is `outer(3)` bound to a name and then both printed and
called:

```python
def outer(a):
    def inner(x):
        return x + a
    return inner

f = outer(3)
print(f)
print(f(10))
```

CPython 3.14.7 prints `<function outer.<locals>.inner at 0x...>` then `13`.

## What the generated C says, and it is exact

    void _toplevel (void)
    {
      MojoBoundMethod * _t1;
      ...
      _t1 = outer_9f63a2 (_t2);        /* the closure value */
      _t3 = _t1;
      _root_globals.f = _t3;           /* the STORE — into a field */
      _t4 = _root_globals.f;
      sprintf (_t5, _slit_10000, _t4); /* `%s` on a MojoBoundMethod * */
      mojo_print (_t5);
      ...
      _t10 = mojo_bound_method_call_1 (f, ...);   /* the CALL — a BARE name */
    }

Two independent defects are visible in eight lines, and each is a build
failure rather than a wrong answer, which is why this is cheap to see and was
never noticed:

1. **`_root_globals` has no field `f`.** `f = outer(3)` is a MODULE-SCOPE
   assignment, so `_gen_stmt_AssignStmt` routed it to this module's globals
   struct (`_root_globals.f = ...`) instead of declaring a local — correct in
   principle, and it is the same route every module-level `X = ...` takes. The
   globals struct's fields come from the module-scope pre-scan
   (`_scan_module_level_for_func_attrs` and the Phase 1.7 global passes), and
   that scan did not record `f`, because the global's inferred type is
   `MojoBoundMethod *` — a type no global pre-pass in this tree appears to
   mint a field for. The comparison `f` undeclared is reported against the
   `#include <stdio.h>` line because the struct member reference is what
   fails, which is why the diagnostic names a header rather than the store.
2. **The call reads the BARE `f`, not `_root_globals.f`.** Every read in the
   same block correctly goes through the struct field (`_t4 =
   _root_globals.f`), so the write and the read disagree about where the
   binding lives. Even with defect 1 fixed this would read an undeclared
   local. The read-side dispatch for a module-scope name is presumably
   keyed on the same pre-scan that failed to record it, so the two are
   likely one root cause — but that is a hypothesis, not a measurement, and
   the next step below is written so it distinguishes them.

## What is NOT the cause, so nobody re-derives it

* **Not the decorator, and not the `print` fix.** Both were checked by
  reverting the decorator-doc commit and re-running: byte-identical failure.
* **Not `MojoBoundMethod *` itself.** The same lowering is correct when the
  closure value is passed straight to a call or handed to another function —
  `mojo_bound_method_call_1` and `mojo_bound_method_new` are both emitted,
  and `emit_exprs`' `_lower_bound_method_value` path is what produced them.
  It is the STORE INTO A NAME at module scope that is unhandled.
* **Not a memory or resource failure.** Peak 0.3 GB, 0.2 s, exit non-zero on
  a gcc parse error.

## Exact next step

1. Reproduce at the narrowest possible size, which this already is: a
   module-scope `f = <any closure value>` is enough; the `print` and the call
   are not both needed to fail. Confirm whether a module-scope local bound to
   a `MojoDict *` or a user `struct *` compiles — if those do, the gap is
   specific to `MojoBoundMethod *`; if they do not, it is "a global whose type
   comes from a call", which is much wider and belongs to the global pre-scan.
   **That single question decides which of the two fixes below is right, and
   it is a two-line experiment.**
2. Whichever it answers, the fix is in the global pre-scan that mints
   `_root_globals`' fields (the same family as `_scan_module_level_for_func_attrs`
   and `_global_var_types`): record a `MojoBoundMethod *` field for a
   module-scope name bound to a closure value. Not in `_gen_stmt_AssignStmt`'s
   store arm, which is already doing the right thing by routing to the struct.
3. Re-check the bare-name read afterwards. If it is still bare after (2),
   defects 1 and 2 are two root causes and the read-side dispatch needs its
   own fix; if it resolves with the field, they were one.

Cheapest verification once fixed: `compile_to_gimple` + `gcc -fgimple` + run
on the fixture above, compared against CPython on the same text — the same
harness `test_gimple_runner.py` uses. A regression belongs in
`test_gimple_runner.py` beside its other closure cases, or in
`test_gimple.py` if the assertion is on the emitted C rather than the output.

## Why this was not fixed here

`gimple_codegen.py`, `module_gen.py` and `emit_exprs.py` were already carrying
this branch's two other fixes, and the global pre-scan is the exact machinery
`bugs/CODEGEN_multi_kind_global_read_before_the_reassignment_reads_the_placeholder.md`
(another claim) is about. Landing a third change to the same pass from here,
without the measurement in step 1, is how a global-field change turns into a
silent wrong value in a stdlib module — which is the failure mode
`bugs/PARTIAL_WORK_HANDOFF.md` §2.1 records at length.