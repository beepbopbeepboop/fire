# A def that returns a bare imported `str` global is typed `int64_t`

## Status (2026-11-22, LAND-gate-bootstrap-stage2-cc-3): export half landed on master

Ported from `work/bug-gate-bootstrap-stage2-cc-3` (`216004a13`): the `module_loader.py`
str-literal export (`_ml_plain_str_literal`) and its pin
`test_imported_global_stub.py::test_py_str_literal_global_is_read_through_accessor`
(fails on master before the port, passes after). The definer-side return below is
NOT changed by that port and is still open. The branch's `gimple_codegen.py` /
`gimple_codegen.py` / `emit_funcs.py` / `module_gen.py` attempt at the definer-side
return was dropped (see the commit that deleted `bugs/LAND-gate-bootstrap-stage2-cc-3.md`
for the reason): it is not landed, and its effect on this repro was not measured
against master.

## Status (2026-11-21, work/bug-gate-bootstrap-stage2-cc-2): partial fix landed

**Landed:** `module_loader._ml_py_global_ctype` now types an unannotated
whole-RHS plain string literal (`NAME = 'x'`, `_ml_plain_str_literal`) as
`char *`, the type the defining module's accessor already has. Before, such a
global was left UNEXPORTED, so an importer read it through no declaration at
all: `cas.ABI_VERSION` compiled to `_t1 = (int64_t)0;  /* ct param or
undeclared */` (a silent NULL). After: `extern char * cas__mojo_global_get_
ABI_VERSION (void);` and a real accessor read. Pinned by
`test_imported_global_stub.py::test_py_str_literal_global_is_read_through_accessor`
and the rule assertions in `test_py_scalar_global_scanner_...`.

**Still open (the repro above is NOT fixed):** the export scan only runs for
`.py` modules in the compiler's own directory (`_selfhost_gate` in
`module_loader.py`), so the `k_src.py` fixture in `/tmp`-style trees still
gets the importer's `int64_t` stub. Every compiler-module instance in the
closure is inside the gate, so the closure is covered; the general case (a
definer outside the compiler directory) is still the ordering fix the plan
below describes. The `_reconcile_imported_global_accessors` ordering fix
(option b) is not done.

Found while measuring the residual gaps of `bugs/gate-bootstrap-stage2-cc.md`
(round 5, 2026-11-21). Not the job's cause on its own; a separate defect in the
same inference path.

## Repro (unit scale, no fixture from the closure needed)

Definer `k_src.py`, importer-side unit `d_def.py`:

    # k_src.py
    NAME = "s"

    # d_def.py
    from k_src import NAME

    def f(x):
        return NAME

`gimple_codegen._run_pipeline(d_def_src, do_imports=True)` emits:

    int64_t f_9f63a2 (int64_t x)
    {
      char * _t1;
      ...
      _t1 = _k_src_globals.NAME;
      _t3 = (void *)_t1;
      _t4 = (int64_t)_t3;     /* return value is the pointer bits, cast to int */
      ...

`gcc -fgimple -fsyntax-only` accepts it (rc 0), so nothing stops it. The
definer's OWN `NAME` is `char *` (its accessor is `char * k_src__mojo_global_
get_NAME (void)`), so the definer's own return type is wrong: a caller of `f`
gets an integer where it expects a string.

Same-module `G = "s"; def f(x): return G` is correct (`char *`), so the bug is
specific to a bare name whose home is an IMPORT.

## What is known (measured)

* The definer's accessor type for the imported name is correct once it
  is reconciled: `_reconcile_imported_global_accessors` (`emit_infra.py`
  ~1997) exists to replace the text-scan type with the home module's
  `_module_globals` type.
* The return-type inference for `f` runs BEFORE that reconcile, reads
  `gen._imported_global_accessors[NAME]` (`resolve_shared._quick_type`,
  ~line 323), and gets the text-scan answer `int64_t`
  (`module_loader.py` export scan, `c_return_type` default at ~1012).
* `_reconcile_imported_global_accessors` is called at `module_gen.py:20394`,
  after the prototype/return of `f` were already written (the prototype
  `int64_t f_9f63a2 (int64_t x);` is the first thing emitted for `f`).

## Next step

1. Pin it: a case in `test_gimple_function_scoped_import_extern.py` (or a
   sibling `test_*.py` for return inference) asserting the definer's
   `f_9f63a2` return is `char *` for the repro above. Expected to FAIL today.
2. Fix the ORDER, not the table: make the imported-global accessor type
   available to the return inference before `f`'s prototype is emitted. Two
   candidate shapes, decide by reading `module_gen.py` around 14215 vs the
   prototype pass:
   a. Have `_emit_imported_global_accessors` take the home module's
      `_module_globals` type (the same source the reconcile uses) when the
      home module is loadable, so the first write is already right; or
   b. Run the reconcile before the function-prototype pass.
   Option (a) is preferred: it removes the second write rather than moving it.
3. Gate-level check when the owner runs it: the importer extern for `f` must
   equal the definer's prototype, and `stdlib-dylib` skip count must not rise.

## Scope

Affects any unannotated def returning a bare name imported as a `str`
(or other non-int) global. Whether the closure itself hits it is measurable
only by the artifact grep in `bugs/gate-bootstrap-stage2-cc.md`.

## Status (2026-11-22, work/bug-gate-bootstrap-stage2-cc-3): root cause measured, ordering fix NOT landed

Measured at unit scale on this tree (repro above, fixture under `build/` so
the sibling resolver can see it; `_run_pipeline(..., do_imports=True)`):

* The importer's `_imported_global_accessors` is EMPTY for `NAME`.
  `_emit_imported_global_accessors` (`emit_infra.py` ~1854) resolves `k_src`
  through `gen._local_sibling_module_exports` → `gen._parsed_import`, which
  does not find a fixture that is not a compiler sibling. So the export entry
  never reaches the table, and `_quick_type`'s bare-name branch
  (`resolve_shared.py` ~323) falls through to its `int64_t` default.
* The definer's `_module_globals['k_src']` DOES hold `NAME: char *` by the
  time `_reconcile_imported_global_accessors` runs (module_gen ~20394). It is
  too late: the return inference for `f` runs at `_gmp_infer_return_types`
  (module_gen ~15795), before Phase 1.7 (~19812+) writes the own overlay and
  before the reconcile.
* Tried and REVERTED (no change landed): calling the reconcile right after
  `_gmp_compile_imports` (module_gen ~14284). It does not move this repro,
  because the importer's table is empty there too — nothing to reconcile.

Corrected next step (replaces option (a)/(b) above, which do not reach the
cause for this shape):

1. Make the bare-name answer in `_quick_type` consult the HOME module's
   `_module_globals` for an imported name that has no accessor entry, using
   the definer's `_imported_global_module` mapping (set when the definer is
   compiled into the unit). Or, equivalently, register the accessor from the
   home module's parsed statements when `_parsed_import` resolves it.
2. Pin it first: a case in `test_gimple_function_scoped_import_extern.py`,
   fixture under `build/test_gimple_function_scoped_import_extern/` (NOT
   `$TMPDIR`), definer `k_src.py` = `NAME = "s"`, importer `def f(x): return
   NAME`, assert the definer's own `f` prototype is `char *`. Fails today
   (`int64_t`).
3. Caveat for the verification: a real compiler-sibling home (`cas.py`,
   `ABI_VERSION = "2"`) pulls its whole import closure under `do_imports=True`
   — the probe ran past 120 s and was stopped. Use a leaf-sibling fixture
   or the `do_imports=False` shape with a sibling export to keep the quick
   test cheap.

## Status (2026-11-22, work/bug-gate-bootstrap-stage2-cc-4): the ordering fix cannot reach this repro; the open part is a scope decision

Measured on this branch (`.tmp/probe/k_src.py` = `NAME = "s"`):

    python3 -c "import module_loader as m; print(m._module_loader.load_module_from_path('.tmp/probe/k_src.py'))"
    -> {}

The export scan that types `NAME` as `char *` (module_loader.py ~1216-1220,
the scalar loop at ~1313-1330) runs only when the file's directory is the
compiler's own `_selfhost_dir`. A fixture outside it exports NOTHING, so
`_emit_imported_global_accessors` (emit_infra.py ~1854) has no entry to write
and `_quick_type` answers `int64_t` by default. That is why option (a)/(b) and
the `_quick_type` home-globals idea in the section above cannot change this
repro: there is no export to reconcile and no `_parsed_import` to read.

What is true for the production closure: every compiler sibling IS inside the
gate, so its str-literal global exports `char *` (216004a13, pinned by
`test_imported_global_stub.py`) and the importer's `_imported_global_accessors`
is filled from that export. The `return NAME` divergence the job needs is
therefore closed for the closure by the export change, and what remains is only
a definer OUTSIDE the compiler directory.

**Decision the owner must make (no code landed for it):**

* A. Broaden the gate: scan `.py` exports for any local project sibling that
  the import resolver reaches, not only `_selfhost_dir`. Cost: every such
  module gets a text-scan export it did not have; the `stdlib-dylib` skip
  count and `compile_stdlib.py`'s `U` must be compared before/after (the
  integrator's run). Plan: change the gate condition at module_loader.py:1216
  to `path.endswith('.py')` plus a directory check that matches
  `_local_sibling_module_exports`; add a fixture case to
  `test_imported_global_stub.py` asserting `k_src` exports `char *`; then the
  case-2 repro in this doc becomes a green test.
* B. Keep the export gate as it is (closure-only, by design), close this doc
  as "closure-covered" once the job's artifact grep shows no `int64_t` extern
  for a str global, and file the outside-dir case as a known scope limit.

Recommendation: B, unless the artifact grep shows a str-global extern. The
gate is the closure, and A widens every stdlib-adjacent `.py` scan for a case
no shipped module has.
