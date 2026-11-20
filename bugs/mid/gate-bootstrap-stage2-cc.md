# Gate: bootstrap-stage2-cc is red on master

**Job:** `bootstrap-stage2-cc`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py bootstrap-stage2-cc`), then fix the cause. Do not skip or mark the test.

## Status (2026-11-18, work/fix-gate-bootstrap-stage2-cc)

The original red had TWO independent classes of gcc errors:

1. **FIXED (this branch):** the function-scoped (method-body) import
   `from mojo.middle.types import param_annotation_ctype` in
   `module_loader.ModuleLoader._mojo_type_to_c` — the import-extern
   preamble ran after the function scope popped and the param half
   (`_imported_def_pts`) had no last-resort tier the name half had, so
   the call site (`..._9f63a2`) and the preamble declaration disagreed
   (`implicit declaration` at module_loader.py:1511 + `conflicting
   types` at regex_compile.py:531). Fixed in
   `mojo/backend_gimple/emit_funcs.py` (`_imported_def_pts`); regression
   `test_gimple_function_scoped_import_extern.py` (suite job
   `reg-gimple-function-scoped-import-extern`), verified failing on the
   old code and passing on the new. The same rerun also fixed a third,
   trivial class: `_commit_home_def_pts`'s stale `-> None` annotation
   (it returns the node's signature list) made the bootstrap declare
   `_def_pts` void in gen_func (4 errors).
2. **STILL RED (pre-existing, separate):** two container-typing defects,
   documented and filed:
   - `bugs/CODEGEN_frozenset_global_decl_word_vs_ptr.md` — the
     `frozenset` global `_COMPTIME_TYPE_FUNCS` is an `int64_t` word in
     `fire_compiler.py` but `MojoSet *` in `ownership_check.py`
     (3 errors);
   - `bugs/CODEGEN_set_op_operand_typed_double.md` — the set-typed loop
     local `kinds` in `mojo/middle/coro.py`'s
     `_scan_callsite_param_kinds` is lowered as `double` for the
     `kinds - {None}` operand (2 errors).

Until class 2 lands, the job stays red and this doc stays.
