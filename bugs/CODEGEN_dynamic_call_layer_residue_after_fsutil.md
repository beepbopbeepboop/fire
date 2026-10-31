# Residue of the dynamic call/iteration layer for compiled generators

Found 2026-10-30 while closing `c_common/fsutil.py` (which now builds, links and
runs; `iter_files`/`walk_tree`/`glob_tree`/`process_filenames` match CPython on
the call shapes below that work). Each item is a small, separate defect with a
repro; none is a regression of that work.

Layer, for orientation: a compiled generator FUNCTION used as a value is its
`<base>_start` address; each C++-path unit registers a runtime signature
(`mojo_gen_sig_register`), `mojo_dyn_call` binds positional/keyword arguments by
name, and `mojo_iter_word` drains a handle it started. Generators that are used
as values, or that call one of their own parameters, are kept on the C++ path
(`coro._eligible`).

## Status (2026-10-30)

- **Item 1 FIXED** (`test_link_mode.py::test_bare_submodule_import_keyword_call`).
  The module-alias fallback in `emit_methods._lower_method_call` carried a
  `not node.kwargs` guard, so `mod.gen(..., kw=...)` / `mod.f(..., kw=...)`
  fell through to the module-marker stub (`mojo_module_not_compiled`). The
  fallback already forwards kwargs into the bare-name call, so the guard was
  the defect; removed. Measured before/after: test FAIL (rc=1, no output) ->
  PASS (`0 10 20 30 15`, CPython-identical).
- **Item 2 NOT REPRODUCED in minimal form** on this tree (verified 2026-10-30):
  `len(list(lib.counter(4, step=10)))` in a package prints `4` (CPython `4`).
  Full `c_common/fsutil.py` link-mode reproduction exceeds quick-test budget
  (compile >2 min). Next step unchanged: reproduce with real shape before fix.
- Items 3, 4, 5: not yet started. Quick regression added:
  `test_regress_dynamic_call_layer_residue.py` (item 1 verified via
  `test_link_mode.py::test_bare_submodule_import_keyword_call`; item 2
  minimal form passes).

## 1. (FIXED — see Status) `mod.gen(..., kw=...)` through a module attribute

    from c_common import fsutil
    for f in fsutil.walk_tree("runtime", suffix=".h"): ...

compiled, then died at run time with `NotImplementedError: ... module
'c_common.fsutil' is not compiled into this binary`. Fixed as above.

## 2. `list(mod.gen(...))`

`len(list(fsutil.walk_tree("runtime")))` raises the same NotImplementedError: a
module-attribute generator call used as an ARGUMENT is not recognised as a
generator construction.

## 3. A bool result off an unsolved word prints `1`

    for f in iter_files("runtime", ".h", "."):
        print(f.startswith("runtime"))     # CPython: True; compiled: 1

`f` is the unsolved word a registered generator yielded; the method call on a
word returns an int and loses the bool kind.

## 4. try/except after an earlier loop over an empty generator

    def im(items, onempty=None):
        if not items:
            if onempty is None:
                return
            raise ValueError("empty")
        for item in items: yield item, True
    for a, b in im([]): print(a, b)
    try:
        for a, b in im([], "msg"): print(a, b)
    except ValueError as ex: print("caught", ex)     # compiled: Unhandled exception

Reproduces without any of the dynamic layer (`if len(items) == 0:` too); the
consumer's `setjmp`-based `try` is not entered correctly after an earlier
`return`-terminated generator loop in the same function.

## 5. Generators with `double` parameters have no runtime signature

`_cpp_generator_sig_lines` declines a unit with a `double` parameter (it would
travel in a float register, which the word-typed `_gen_sig_call` cannot
reproduce), so such a generator used as a value and called with keywords raises
a catchable `TypeError`. A signature carrying per-parameter kinds, and a call
thunk per arity/kind shape, would close it.

Quick test for items 1-3: build `.tmp`-style copy of CPython's `c_common` and run
the three snippets above against CPython.
