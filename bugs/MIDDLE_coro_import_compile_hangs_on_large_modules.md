# MIDDLE_coro_import_compile_hangs_on_large_modules: do_imports compile hangs in coro/literal_bindings on compiler-sized modules

**Status:** NEW — found 2026-11-08 while fixing `SUITE_sqliteruntime` (the
`sqliteruntime` suite job timed out because `test_sqlite3_runtime.py`'s
`test_probe_ignores_mentions` exercised this path).

## Repro
From the repo root:
```sh
python3 - <<'PY'
import sys, faulthandler; sys.path.insert(0,'.')
faulthandler.dump_traceback_later(30, exit=True)
import gimple_codegen
gimple_codegen.compile_to_gimple_cached(
    'from build_config import find_gcc\n'
    'def main():\n    print(find_gcc())\n',
    do_imports=True, filename='probe.mojo')
PY
```

## Observed
Hangs (no completion within 30s+). `faulthandler` shows the stack cycling
through `mojo.backend_gimple.emit_resolve._compile_imported_module` /
`module_gen.gen_module_impl` / `gimple_codegen._compile_imported_module`
while compiling transitive imports, and stuck inside
`mojo.middle.coro._scan_callsite_param_kinds` -> `_one_pass` -> `_collect`/
`_collect_from` -> `_module_literal_env` ->
`mojo.middle.literal_bindings.binding_index`/`bound_names`
(`mojo/middle/literal_bindings.py:77,114,144`; `mojo/middle/coro.py:5266,5664`).
One trace also showed a hang in `fire_compiler.replace_multiline_strings`/
tokenization during `_seed_selfhost_module_globals`, suggesting the
transitive `do_imports` closure over compiler-sized modules
(`gimple_codegen` itself appears in the compiled set) is pathologically slow
or looping.

## Expected
`compile_to_gimple_cached(..., do_imports=True)` completes (or fails fast) on
a small module whose imports pull in `build_config`/compiler modules.

## Impact
Any real `do_imports=True` compile that reaches compiler-sized modules can
hang. Surfaced as the `sqliteruntime` suite timeout.

## Next step
Trace why compiling `gimple_codegen` (module #17 in the traced import
closure for this snippet) enters an apparently non-terminating
`binding_index`/coro scan: check `literal_bindings.bound_names`/
`_walk_ast` for cycles or quadratic behavior on large ASTs, and check whether
`_module_literal_env`/`_scan_callsite_param_kinds` re-triggers module
compilation or lacks a visited/guard set across the import closure. Fix the
non-termination in `mojo/middle/literal_bindings.py` and/or
`mojo/middle/coro.py` (and `module_gen`/`emit_resolve` if re-entry is the
cause), then restore `test_sqlite3_runtime.py::test_probe_ignores_mentions`
to a `do_imports=True` import-snippet form if desired.
