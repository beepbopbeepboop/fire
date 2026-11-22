# CODEGEN: the stage2 binary raises `AttributeError: _as_comptimevar_node` on every dump

Found 2026-11-21 while running `make bootstrap` on master plus the stage 5b WordFacts work.
Stage1 (`stage1/fire.ci`) now links and stage2 (`stage2/mojo`) links and starts, but
every `bootstrap-stage2-dumps` job exits 1 with:

    Unhandled exception: AttributeError: _as_comptimevar_node

## What the statement was

`mojo/middle/comptime.py` bound the helper as a module attribute:

    import fire_compiler as _fc
    _as_comptimevar_node = _fc._as_comptimevar_node

`_as_comptimevar_node` is a plain top-level function of `fire_compiler.py` (line 4815);
`mojo/backend_gimple/emit_funcs.py:32` imports it by name. In a compile that does not already
know `fire_compiler`'s defs — the per-file `do_imports=False` shape, and the compiled binary's
own module-by-module closure walk when the defining module has not been reached yet — a
`<module alias>.<member>` read used as a VALUE fell through `_lower_MemberExpr`'s function-value
branch (gated on `node.member in gen.func_return_types`) to the generic dynamic-dispatch
fallback. That fallback reads the attribute off the module marker, whose value is `0`:

    _t102 = (void *)_root_globals._fc;   /* module marker: 0 */
    _t104 = _slit_10199;                 /* "_as_comptimevar_node" */
    _t103 = _mojo_dispatch_getattr (_t102, _t104);

so the statement was a fatal, uncaught `AttributeError` the instant the module initialized —
before any dump work. Introduced by `010f47e2b` (comptime: fold an APPLICATION of a generic
comptime alias, 2026-11-17) and the `_as_comptimevar_node` helper in `e8a7135b8`.

## Root cause, and what is fixed

The defect is in the lowering, not in `comptime.py`: a function read as a VALUE through a real
module alias must resolve to the defining module's mangled symbol and the matching extern,
whatever this translation unit happens to know about that module. On this branch:

- `funcs_shared.register_module_member_function` is now the ONE writer for
  "`<alias>.<member>` names a function of the module the alias holds", shared by the
  module-qualified CALL path (it absorbed `emit_methods._register_sibling_module_member`'s
  steps, so there is no second copy to drift) and by the VALUE path
  (`_lower_MemberExpr` / `calls_shared._callable_value_symbol`).
- It resolves the definer and its original name through ONE hop walk
  (`_find_symbol_home_module(..., want_name=True)`), so a re-export that RENAMES
  (`from impl import double_it as dt`) still yields the DEFINER's qualifier + overload suffix
  for `_func_csym`, and the extern the import pass emits matches it.
- `_callable_value_symbol` no longer treats a module alias's member as shadowed by a local or
  module-level name of the same spelling (an attribute of a module is not shadowed), and it
  registers the member on demand instead of requiring it in `func_return_types`.

Upstream `5128d44f3` had already rewritten the `comptime.py` statement to
`from fire_compiler import _as_comptimevar_node` (a direct import, which works); that removed
the MEASURED symptom from the closure without touching the lowering defect. The pin below is
built on the general shape (`f = h.double_it`, `f = h.dt`, the call spellings, a parameter
default, a function-scoped import), not on that one file.

## Done when

1. **Quick (the pin):**

        python3 tools/memslot.py --gb 8 --label x -- python3 test_codegen_module_alias_function_value.py

   passes. It compiles each fixture module with `build_stdlib_dylib.compile_module_to_c`
   (the per-file `do_imports=False` shape), links every module with `runtime/fire_runtime.c`
   and RUNS the result, comparing against CPython. **This passes on this branch.**
2. **Full:** `make bootstrap` gets past `bootstrap-stage2-dumps` (stage2 dumps all exit 0),
   then `bootstrap-verify` compares stage1 / stage2 / stage3 byte for byte. Delete this doc in
   the commit where the full chain is green.

## Status 2026-11-21 (worker round)

- **Landing this round (branch `work/bug-codegen-selfhost-stage2-attributeerr`):** the
  lowering fix and its pin (`test_codegen_module_alias_function_value.py`); the doc is kept
  because criterion 2 is still unreachable here.
- **Measured, quick test:** before the fix (tree at `946f2d099^`) it fails with
  `AttributeError: double_it` / `AttributeError: dt` for the value spellings and
  `NotImplementedError: helper.dt: module 'helper' is not compiled into this binary` for the
  call spellings; after the fix all 6 shapes print CPython's answer. The generated C carries
  `_funcptr_*double_it_*` and no `dynamic-getattr` string for the member.
- **Measured, covering existing tests:** `test_link_mode.py` 56 passed, 0 failed (covers
  `_compile_imported_module`, sibling-export lookup and bare-import calls, which share the
  rewritten writer); `test_star_reexport_resolution.py` PASS.
- **Measured, closure sweep:** all 52 compilable self-host modules (`gimple_*.py`,
  `mojo/middle/*.py`, `mojo/backend_gimple/*.py`) compiled per-file: after the fix, **zero**
  module-alias attribute reads lower to `_mojo_dispatch_getattr` (the fatal marker read). The
  one module that does not compile per-file, `emit_stmts.py`, fails on a pre-existing
  generator-shape limit unrelated to this bug.
- **Why criterion 2 cannot run here:** master DISABLES `bootstrap-stage1-transitive` and
  `bootstrap-stage2-cc` (their docs `bugs/gate-bootstrap-stage1-transitive.md` and
  `bugs/gate-bootstrap-stage2-cc.md` are the switches). `bootstrap-stage1-dumps` therefore
  leaves `stage1/fire.ci` as the per-file dump of one module (604 KB, not the ~135 MB
  closure), so `stage2/mojo` is a skeleton, and `bootstrap-stage2-dumps` runs it rather than a
  stage2 built from a full stage1. Re-enabling those two jobs (their own lanes) is the next
  step; then rerun the stage2 dump fanout and `bootstrap-verify`.
- **Adjacent, still open, NOT needed for this statement:**
  `bugs/CODEGEN_module_alias_attr_per_file_remaining_shapes.md` records three per-file
  module-alias shapes that are still wrong (a same-named class in the importer shadowing a
  module member function; a class VALUE read through an alias; a class-body attribute bound to
  a module-alias function value).
