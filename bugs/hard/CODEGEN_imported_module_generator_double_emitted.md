# HARD BUG: an imported module's generator function can get compiled+emitted twice

## Status

Unfixed. Confirmed real and reproducible; root cause partially diagnosed
(one likely mechanism ruled out), not fully traced.

## Symptom

```
error: conflicting types for '<module>_<function>'; have 'void(void)'
```
— the SAME generator function's C++20 coroutine unit appears twice in the
assembled `.cpp` output, at two different original-source line numbers,
with an identical signature.

## Repro

`Modules/_decimal/tests/randfloat.py` defines exactly ONE
`def test_boundaries():` (a generator, contains `yield`). Compiled as the
ROOT module, it's (correctly) refused outright:

```
$ python3 mojo.py build Modules/_decimal/tests/randfloat.py
Error building: cannot compile module: function(s) test_boundaries
(generator function(s), contain a `yield`/`yield from`) — ...
```

But compiled as an IMPORTED module (`Modules/_decimal/tests/randdec.py`
does `from randfloat import un_randfloat, bin_randfloat, tern_randfloat`),
the exact same function is NOT refused — it's accepted into the C++
coroutine path, but its generated `.cpp` text is emitted TWICE:

```
$ python3 mojo.py build Modules/_decimal/tests/randdec.py
.../randfloat.py:54:6: error: conflicting types for 'randfloat_test_boundaries'; have 'void(void)'
.../randfloat.py:83:6: error: conflicting types for 'randfloat_test_boundaries'; have 'void(void)'
```

(Line numbers 54/83 in the generated `.cpp`, not the original `.py` — two
distinct emission sites for the same logical function.)

## Root cause (partial diagnosis)

The two call sites of `_compile_imported_module` in `gen_module`
(`do_imports=True`'s Phase 0 loop, and the separate `link_imports`
fallback loop) BOTH correctly guard against re-compiling the same module
via a shared `self._compiled_modules` set — ruled out as the mechanism
here; a module is never entered into either loop twice.

The duplication must therefore originate INSIDE `_compile_imported_module`
itself, or inside the generator-discovery passes it triggers (`gen_module`'s
free-function generator loop runs up to 3 passes — "some may have had
yield-from dependencies that weren't compiled yet in the first pass" — each
pass's own `_generator_fns.pop(id(s), None)` removes a successfully-compiled
generator by the Python `id()` of its AST node; if the SAME logical
function's AST node has a DIFFERENT `id()` across two different
compilation contexts — e.g. re-parsed independently rather than reusing a
cached AST — the pop wouldn't recognize it as already-handled). This is a
plausible mechanism but NOT confirmed by tracing actual `id()` values or
adding instrumentation — a real next step, not done here.

## Why root-module vs imported-module behavior differs

Not diagnosed. The root-module path's upfront `module_may_have_supported_
generator`-style pre-check (which refuses the WHOLE module if ANY
generator is unsupported) and the imported-module path apparently use
different acceptance criteria for the exact same function shape — this
asymmetry itself might be intentional (imported modules perhaps degrade a
single unsupported generator to a stub rather than refusing the whole
transitively-compiled program) or might be the same underlying bug wearing
a different face. Not investigated further here.

## What a real fix needs

1. Instrument (or read very carefully) `_compile_imported_module` and the
   generator-discovery passes it triggers to find the actual double-entry
   point — confirm or rule out the `id()`-based dedup hypothesis above.
2. Once found, either dedupe by a STABLE key (module name + function name)
   instead of Python object identity, or fix whatever causes the same
   function to be visited by two independent compilation attempts.
3. Re-verify against the `randdec.py`/`randfloat.py` repro above.

Not attempted here — likely intersects with the same nested-module-
compilation architecture flagged in `PERF_nested_module_compile_walk_ast_
quadratic_rescan.md` (both point at `_compile_imported_module`'s handling
of the same underlying state), so a real fix for either might be best
tackled together with a proper understanding of that whole flow.
