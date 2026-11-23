# CODEGEN: a module-alias-qualified module-level global read is a dynamic getattr on the NULL marker (replan part 2 of 4)

## Goal

In the per-file (`do_imports=False`) compile, a module-level global read through an alias —
`import helper as h` then `print(h.CONST)` — must load the defining module's value through its
`helper__mojo_global_get_CONST` accessor instead of falling to
`_mojo_dispatch_getattr` on the alias's NULL module marker.

The test uses an ANNOTATED global (`CONST: int = 41`) on purpose: the export entry and the
accessor already exist for that spelling (measured below), so this part does not depend on
part 1 and is not blocked by it.

## Where and what was measured (2026-11-23)

Fixture: `helper.py` = `CONST: int = 41\ndef double_it(x: int) -> int:\n    return x * 2\n`,
`main.py` = `import helper as h\nprint(h.CONST)\n`. Both compiled through
`build_stdlib_dylib.compile_module_to_c`, linked with `runtime/fire_runtime.c`, run.

- The importer's C carries `static char * _slit_10000 = "CONST";` and
  `_t3 = _mojo_dispatch_getattr (_t2, _t4);` where `_t2` is the module marker `(int64_t)0`.
  The program exits 1 with `Unhandled exception: AttributeError: CONST`.
- The same value spelled `from helper import CONST` (annotated) PASSES and prints `41`, so
  `module_loader`'s export entry and the definer's accessor are both available; only the
  alias-qualified read and its accessor registration are missing.

Where:

- `mojo/backend_gimple/emit_infra.py::_emit_imported_global_accessors` consumes only
  `FromImportStmt`; an `ImportStmt` (`import helper as h`) never registers the name in
  `gen._imported_global_accessors`.
- `mojo/backend_gimple/emit_exprs.py::_lower_MemberExpr`'s module-alias branch
  (`module_name in gen._module_alias_names`) asks only `_callable_value_symbol`, so a data
  global falls through to the generic dynamic-dispatch fallback.

## Next step

Register the accessor for a module-alias `ImportStmt` from the same sibling export table
(`gen._local_sibling_module_exports`), with the same
`<home module>__mojo_global_get_<name>` symbol and C type the `from` spelling already uses, and
route a member read through it in `_lower_MemberExpr`'s alias branch before the dynamic
fallback. The branch must stay behind the existing answers: a function
(`_callable_value_symbol`), a class, a submodule (part 3), and a name this module binds itself
must not be taken over by the accessor.

## Acceptance

- `import helper as h; print(h.CONST)` prints `41`, and the importer's C contains
  `helper__mojo_global_get_CONST` and no `_mojo_dispatch_getattr` whose attribute string is
  `"CONST"`.
- The shapes that already work keep working, in the same test file: a function VALUE
  (`f = h.double_it`), a class value (`W = h.Widget`), a function-scoped import
  (`def go(): import helper as h; return h.CONST`) and the bare
  `from helper import CONST` spelling.
- A name this module binds itself after the import is still this module's (Python shadowing),
  and a function of the aliased module is still answered by the function machinery, not the
  accessor.

## Done when

File: `test_codegen_module_alias_global_read.py` (new).

Command:

    python3 tools/memslot.py --gb 8 --label module-alias-global-read -- python3 test_codegen_module_alias_global_read.py

It builds each fixture through `compile_module_to_c`, links with `runtime/fire_runtime.c`, runs
it and compares stdout with CPython. RED on HEAD at the alias-qualified scalar case
(`AttributeError: CONST`), GREEN after this part.
