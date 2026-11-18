# SUITE: `test_dual_cpp_elaboration.py`'s Trace case uses an undeclared fixture type

**Status (2026-11-17): open. Pre-existing on master; found while landing the
nested-bracket generic-call fix, which does not touch this test.**

## What I ran

    python3 test_dual_cpp_elaboration.py

## What I saw

    Results: 5 passed, 1 failed

The failing case is `test_trace_and_comptime_and_abort_inside_nested_async`:

    /.../prog.mojo:18:10: error: use of unknown declaration 'Trace'
        with Trace[level]("c", "d"):
             ^~~~~

The test source deliberately omits `Trace`/`TraceLevel` ("modulo real
Trace/TraceLevel stdlib imports, which pull in unrelated GPU/DeviceContext
machinery out of scope here") because codegen elides the guard as a no-op
(`gimple_codegen._ASYNC_NOOP_LOCK_GUARD_TYPES`). That elision is in the backend,
but `unknown_decl_check.check_module` runs first and now correctly refuses a
build whose source reads an undeclared name — so the fixture no longer compiles.

## Expected

The test to build and print `33`. The elision under test is a backend no-op,
which does not require the fixture to leave the type undeclared.

## Exact next step

Add a minimal declaration to the test's `src` so `Trace[level](s1, s2)` is a
declared name — a `struct Trace[level: Int]:` whose `__init__(s1: String, s2:
String)` and `__enter__`/`__exit__` are empty (the guard is elided anyway), or,
if the elision is keyed on a type name alone, an `alias Trace = ...` plus the
callable shape the test already relies on. Then `python3
test_dual_cpp_elaboration.py` should report 6 passed, 0 failed. The file is not
registered in `tools/suite.py`, so no bucket was watching this one; consider
registering it (it is a cheap build-and-run file) when it is fixed.
