# IMPORT_ambiguous_sibling_function

## Summary
When a program's two different sibling modules each define a free function with the same name, and the reference
is not lexically bound by any `from ... import`, fire must refuse it. Two shapes are involved:

- **Refused shape (partially fixed 2026-11-12):** two function bodies each `from`-import a same-named fn from two different
  siblings; a third function references the name with no enclosing import. fire previously compiled this silently to
  whichever sibling was registered last (commit cee74d745 had removed the refusal and fell through to the shared
  registry). It is refused again with `error: import of '<name>' is ambiguous: ...`.
- **Still silent (open):** see Status.

## Source (CPython 3.15.2)
The doc was filed from a partial CPython 3.15.2 scan. `get_pager` is defined in
`_sitebuiltins.py`, `pydoc.py` and `_pyrepl/pager.py` (Homebrew install, `/opt/homebrew/Cellar/python@3.15/3.15.2`).
Those are Python sources, and fire compiles Mojo, so the exact program that produced the original report is not
known. The exact message quoted in the first version of this doc does not exist in the code; the real diagnostic is
`error: import of '<name>' is ambiguous` (test_ambiguous_import_diagnostic.py).

## Done when
`python3 test_ambiguous_import_diagnostic.py` passes, plus a test for the open shape below (NOT YET WRITTEN:
`test_unbound_reference_to_transitive_sibling_fn_fails`). The refused shape is already pinned by
`test_unbound_reference_to_ambiguous_scoped_fn_fails`.

## Status
**2026-11-12: partially fixed.**

Landed:
- `mojo/backend_gimple/emit_funcs.py` `_func_qualifier`: when this instance's own home entry is
  `_AMBIGUOUS_FUNC_HOME` and no lexical scope binds the name, raise the ambiguity RuntimeError again instead of falling
  through to `_imported_func_home`. `_func_home_qualifier` already maps that error to `''` for estimator callers.
- `test_ambiguous_import_diagnostic.py`: `test_unbound_reference_to_ambiguous_scoped_fn_fails` (FAILS before, passes
  after) and `test_scoped_imports_of_ambiguous_fn_each_resolve` (the valid counterpart).

Verified (quick, not the gate): `test_ambiguous_import_diagnostic.py` passes all 5 tests after the fix; the first
test fails on the pre-fix file with `compiled without error`. Not run here: `compile_stdlib.py` / stdlib sweep, and
`test_module_cache.py` SB-1 scope tests, which exercise the same resolver. The integrator gates those.

**Still open (the silent miscompile):** a transitive sibling plus one function-local import.
```
# mid.mojo (imports the sibling's get_pager at module scope)
#   from wildcard_shadow_a import shadowed_fn
#   def relay_fn() -> Int: return shadowed_fn()
# main.mojo
#   from mid import relay_fn
#   def call_b() raises -> Int64:
#       from wildcard_shadow_b import shadowed_fn
#       return shadowed_fn()
#   def g() raises -> Int64:
#       return shadowed_fn()      # NO binding in g's scope: invalid Mojo
```
This compiles with no error. `g`'s call becomes `wildcard_shadow_b_shadowed_fn` (the function-local import in
`call_b`). Measured with a tier trace in `_func_qualifier`: `_own_imported_func_home['shadowed_fn']` is
`wildcard_shadow_b` (not ambiguous) because the transitive `wildcard_shadow_a` registration goes to the SHARED
`_imported_func_home` and never reaches this instance's own map. A function-local import is written into the flat
`_own_imported_func_home` (`_note_own_func_home`, `record_scope=True` still writes the flat map), so it leaks into
functions that lexically do not see it.

Next step (not started): make a function-body import register only into its own frame, so the flat own map holds
module-scope bindings only; then decide what an unbound reference should do when only the shared registry knows the
name (tier 3 currently picks first-claim silently). That second decision is the part to check against the stdlib
sweep (`std/memory/__init__.mojo`'s two `alloc` imports and the SB-1 nested-scope cases in test_module_cache.py rely on
the flat map today), so it needs the integrator's stdlib compile before it lands. Pinned by
`test_unbound_reference_to_transitive_sibling_fn_fails` once written.
