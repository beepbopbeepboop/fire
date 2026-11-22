# CODEGEN: a coro pass-through cycle is reported as a referenced generator

`mojo/middle/coro.py`'s `_ParamFlow` answers "is this argument the tagged
generator?", for `_specialize_mixed_generator_callers` (per-kind cloning of a
callee that receives `g()` at some call sites and something else at others).
Its cycle branch assumes a cycle of parameter pass-throughs is fed:

    # coro.py:1680  _ParamFlow.sources_ok
    key = (fd.name, pidx, consumed)
    if key in visiting:
        return True     # a pass-through cycle contributes no other value

That is wrong for a cycle nothing feeds: two (or more) top-level functions
that call each other with a bare identifier argument (`_cpp_stmt` <->
`_cps_if_stmt`, each passing its own first parameter `gen`) are reported as
"this parameter is the generator at every call site", although no call site
ever passes `g()`.  The set is also never popped, so the answer also depends
on which earlier sibling path visited the key first.

## Measured (2026-11-22, this tree)

Extracting the stage-7 arms of `mojo/backend_gimple/cpp_core.py` with
`tools/extract_arm.py` (commit 89c65d3a1) moved `_cpp_stmt`'s eight
`isinstance` arms into top-level `_cps_*` functions.  The arms contained the
nested `def`s that used to make `_nested` refuse a pass-through walk out of
`_cpp_stmt`, and one arm (`IfStmt`) recursed as a bare `_cpp_stmt(gen, ...)`.
After the extraction, with the IfStmt call still bare:

- `python3 fire.py --dump mojo/backend_gimple/cpp_core.py` (same command that
  takes 15 s and succeeds on the previous commit) spends 142 s and fails:
  `compile_to_gimple failed: maximum recursion depth exceeded`, traceback
  `_specialize_mixed_generator_callers -> _mixed_generator_callee ->
  passed_from_source -> sources_ok -> passed_from_source -> ...`.
- Instrumenting `sources_ok`'s depth: 4 levels on the previous commit, 331 in
  the crashing variant.  The deepest frames are clones of the module-level
  generator expression `__genexp_0` with ever-lengthening names
  (`...____genexp_0_____...`), i.e. the `while True` clone loop at coro.py:2036
  cloning the same callee until a Python `RecursionError` fires before its own
  `budget` check can.
- Printing the mixed-callee hit: on the previous commit
  `_mixed_generator_callee` returns None for `__genexp_0`; with the extraction
  it returns `(_cpp_receiver_ctype, 0)`, and the argument at the site that
  makes it "generator-derived" is the emitter object `gen` passed to
  `_cpp_receiver_ctype`.  `passed_from_source` for that site is True only
  because `_cpp_receiver_ctype` <- `_cps_assign_stmt` <- `_cpp_stmt` <-
  `_cps_if_stmt` <- `_cpp_stmt` closes a `gen` pass-through cycle.

## Worked around, not fixed

The stage-7 commit spells that one recursion `gen._cpp_stmt(...)` (the form
every other call site in the file already uses; the method is a one-line
delegate in `gimple_codegen.py:5685`).  That removes the only bare
module-level call edge and `fire.py --dump cpp_core.py` succeeds in 12 s.
`test_gimple_cpp_core_arms.py` pins that no bare printer call comes back.

The defect is still in `coro.py`: any other compiler module that grows a
cycle of top-level functions passing a parameter by name can make the pass
specialize and clone a callee that never sees a generator.

## Next step

Fix `sources_ok`'s cycle handling, then land a regression test:

1. Conservative: `if key in visiting: return False`, and pop the key on every
   return (`try/finally: visiting.discard(key)`) so `visiting` is a path
   stack rather than a never-popped visited set.  This can only LOSE a
   specialization, which the docstring already calls the intended direction
   ("conservative on purpose").  Measure it with `tools/c_oracle.py check`
   over both corpora; any module that changes specialization shows up as a
   changed companion.  The genuine shape the `True` was for — a mutual
   `a(x)`/`b(x)` pass-through where one site of the cycle passes `g()` — is
   then no longer specialized; that is a missed optimization, not wrong code.
2. Exact: a cycle is fed only when some SCC member has a site whose argument
   is `g(...)`; return that.  More code, and it needs an SCC (Tarjan or a
   two-pass "any direct feed in `visiting`" check), so option 1 first.

Regression test: a fixture module with `def a(x): return b(x)`,
`def b(x): return a(x)`, a module-level generator expression so `passed` is
non-empty, and a third function called as `use(gen)` from inside that cycle;
`compile_to_gimple` must not produce `__genexp_0`-specialized clone names and
must not raise.  Against the current tree it reaches the clone loop (assert on
`_mixed_generator_callee(...) is None`).
