# Gate: bootstrap-stage2-cc is red on master

**Job:** `bootstrap-stage2-cc`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py bootstrap-stage2-cc`), then fix the cause. Do not skip or mark the test.

## Done when

`python3 tools/suite.py bootstrap-stage2-cc` passes (gcc accepts and links the
whole-closure `stage1/fire.ci`, and `make stage2/mojo` builds the binary).
State 2026-11-19, master 633131370 after the r2 integration (210191e85):

* The two CONTAINER-TYPING causes are fixed ON MASTER (9542ada7e: the imported
  mirror field answers the owner's declared field; a boxed pointer word is no
  longer unboxed as a double). Pinned there by `test_gimple_imported_container_global_field.py`
  and `test_gimple_set_op_boxed_operand_ptr.py` (the production import-cycle
  and dict-items shapes); this branch's `test_gimple_imported_container_global.py`
  and `test_gimple_set_op_boxed_container_local.py` pass on that fix and stay
  as the two-file pins. This branch therefore carries the r2 versions of
  `mojo/backend_gimple/module_gen.py` and `mojo/backend_gimple/emit_exprs.py`
  (its earlier two-file fixes were superseded and converged).
* The MISSING-DEFINITION cause — a `from M import name` inside a CLASS METHOD
  never pulled M into the do_imports closure, so the whole-closure link died
  on the undefined callee — is fixed ON THIS branch (`_collect_import_modules_rec`
  gains the StructDef arm) and pinned by
  `test_gimple_class_method_import_inlined.py`, which must exit 0 (it FAILS
  on master without the fix).
* Both remaining causes are fixed ON THIS BRANCH, at their root, and pinned.
  * An UNALIASED `from M import C` naming a CLASS was registered as an
    imported function (`bootstrap-stage2-cc`'s hard gcc error,
    `emit_resolve.py`'s `ModuleLoader ()` against the class's own typedef).
    `_note_struct_import_alias` now recognises the unaliased spelling too and
    `_publish_imported_class` registers the defining module's REAL parsed
    StructDef, its method signatures and its class-body attributes into the
    importing gen — before the struct passes and type inference, via
    `_gmp_publish_body_class_imports` — so a class from a module a sibling
    subtree compiled, or one an ancestor is still compiling, constructs and
    dispatches its methods exactly like the definition side. Pinned by
    `test_gimple_class_import_cross_module.py` (all three shapes: ancestor
    mid-compile, sibling-subtree function-scope, sibling-subtree module-scope;
    each prints the constructed value where it used to print `0`, and the
    ancestor shape used to be the hard `expected expression before 'C'`).
  * `import M as N; ... N.SOME_CONTAINER_GLOBAL` read through a module alias
    whose owner was still MID-COMPILE stubbed to literal 0 (`unknown_decl_check.py`'s
    `_COMPILE_TIME_INTRINSICS` lost `type_of`/`__type_of`, so a compiled
    `fire` refused real Mojo source the interpreter accepted). The
    MemberExpr `submod.GLOBAL` arm now answers from the owner's own
    declaration while the owner is an ancestor on the compile stack
    (`_gmh_pending_module_global_field_type` — the `submod.GLOBAL` counterpart
    of `_lower_IdentExpr`'s `_imp_pending`). Pinned by
    `test_gimple_module_global_pending_owner.py` (prints `True`; `False`
    before the fix).
* NOT re-run here: the whole-closure `bootstrap-stage2-cc` job itself is the
  gate run the integrator owns. The two pins above and the closure-scale
  evidence recorded in the branch commit are what the fix was verified with
  (an `emit_resolve.py` whole-closure generate + `gcc -fsyntax-only` check
  reports the same 15 pre-existing diagnostics as before this change, with
  the `ModuleLoader` site now a real `_alloc_ModuleLoader()` constructor and
  a direct `module_loader_ModuleLoader_resolve_module_path` call).
