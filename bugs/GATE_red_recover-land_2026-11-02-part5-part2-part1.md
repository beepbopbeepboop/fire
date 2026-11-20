# Bootstrap dump chain part 1: a function-scoped sibling import of a string global is not a stub

## Goal

Stop the whole-closure dump from emitting a weak function stub for a module-level
**constant** that a function imports from a sibling module. The measured case is
`cas._stdlib_fingerprint` (`cas.py:581`):

    from module_loader import STDLIB_PATH
    root = STDLIB_PATH if STDLIB_PATH and os.path.isdir(STDLIB_PATH) else None

`STDLIB_PATH` is a module-level string in `module_loader`, not a function. The
function-scoped `from module_loader import STDLIB_PATH` registers the name as an
imported symbol with no signature, so `_gmp_emit_imported_symbol_stubs`
(`mojo/backend_gimple/module_gen.py`) emits

    __attribute__((weak)) int64_t STDLIB_PATH (...) { mojo_print("STDLIB_PATH: unavailable in compiled mode"); ... }

and every use site in the closure compiles to `_funcptr_STDLIB_PATH`. The stage2
binary therefore prints `STDLIB_PATH: unavailable in compiled mode` whenever it
computes the stdlib fingerprint — i.e. on every compile — which is exactly the
`SELFHOST_DUMP_REJECT` pattern that fails every `bootstrap-stage2-dumps` and
`bootstrap-stage3-dumps` item.

Make the function-scoped sibling import of a `global_var` export resolve the way
the module-scope path already does: register/read the defining module's
`<mod>__mojo_global_get_<name>` accessor, so the read is the real global and no
weak stub is emitted. Do not widen the stub skip to symbols the accessor pass
cannot resolve — a missing accessor must stay a hard error, not silence.

## Acceptance

- The whole stage1 closure dump has no `__attribute__((weak))` definition except
  the four documented `_mojo_gpu_*` no-ops. Measured on the integrator tree at
  `48c9115da` (work-integ `stage1/fire.ci`, 2026-11-19 16:00): five weak
  definitions, four GPU no-ops plus `STDLIB_PATH`, with 14 use sites reading
  `_funcptr_STDLIB_PATH`.
- In the emitted C for the fixture, `cas._stdlib_fingerprint`'s body reads the
  `module_loader__mojo_global_get_STDLIB_PATH` accessor (or the module struct
  field), not a function pointer, and the emitted C contains no
  `STDLIB_PATH: unavailable in compiled mode`.
- The fixture builds and runs with CPython's stdout and exit status.
- No new stub skip is added for a global whose accessor is unresolved.

## Done when

File: `test_imported_global_stub.py` (extend its fixture with the
function-scoped spelling: a function body doing
`from owner import STRING_GLOBAL` where `owner` is a sibling module, compiled
with the real `_run_pipeline(..., do_imports=True)` shape the file already
uses).

Command:
`python3 tools/memslot.py --gb 8 --label imported-global -- python3 test_imported_global_stub.py`

It currently takes ~12 s and 0.1 GB. The new case must be observed red before
the fix (the weak `STRING_GLOBAL (...)` stub in the emitted C, or the stub text
in the built binary's output) and green after, together with the existing
module-scope DICT/SET cases.

## Status (2026-11-19, planning round)

Measured on this tree. The doc's premise is only partly right, and the missing
piece is not where the Goal says.

- **The export table has no entry for the measured global.**
  `module_loader.load_module_from_path('module_loader.py')` returns 29 exports
  and no `STDLIB_PATH` key; the only `global_var` is `_C_KEYWORDS`. So
  `_emit_imported_global_accessors` (`mojo/backend_gimple/emit_infra.py`,
  ~1850) has nothing to register for `cas.py`'s `from module_loader import
  STDLIB_PATH`, and `_gmp_emit_imported_symbol_stubs` (`module_gen.py` ~11112)
  emits the symbol as a no-signature import. Reproduced with
  `compile_to_gimple(cas.py text, do_imports=False)`: `extern int64_t
  STDLIB_PATH (...);  /* from module_loader */` plus `_funcptr_STDLIB_PATH`.
  The definer does emit the accessor (`module_loader__mojo_global_get_STDLIB_PATH`
  appears when `module_loader` is compiled in the same unit), so the fix is on
  the importer's export side, not in the accessor pass.
- **The scanner exports only container and set globals from `.py` siblings.**
  `module_loader.py` ~1156-1222: `NAME = frozenset(...)`/`set(...)` in any
  `.py`, and `{...}`/`[...]` literals only in `generated_dispatch.py`
  (`_scan_container_literals`). Its own comment records that a broader match
  produced `conflicting types for 'gimple_codegen__mojo_global_get__RUNTIME_FUNCS'`.
- **Function scope is not the failing shape by itself.** A recursive walk over
  all `FromImportStmt`s (any depth) in `_emit_imported_global_accessors` changed
  no emitted C for a function-scoped `from generated_dispatch import
  _EXPR_DISPATCH` (diff of do_imports False/True output identical, modulo the
  probe directory name). That case already reads
  `generated_dispatch__mojo_global_get__EXPR_DISPATCH`. The walk was reverted
  and is not landed.
- `test_imported_global_stub.py` now also pins the separate-compile
  (`do_imports=False`) function-scoped container import. It passes before and
  after, so it is coverage, not the red reproduction the Done-when asks for.

**Decision needed: the C type of an unannotated module global the scanner does
not type today.** `STDLIB_PATH = _find_stdlib_path()` has no annotation, and
`_find_stdlib_path` has no return annotation (`module_loader.py:465`).

- A. Annotation and literal only: `: str`→`char *`, `: int`/`: bool`→`int64_t`,
  `: float`→`double`, literal RHS by kind. Narrowest. Does NOT cover
  `STDLIB_PATH`, which is unannotated.
- B. A plus the callee-return rule: RHS `f(...)` where `f` is a same-file `def`
  with an annotated return maps through the same table. The mojo `var` branch
  already does this (`module_loader.py` ~1385-1410, `_vcallee_ct`). Covers
  `STDLIB_PATH` once `_find_stdlib_path` is annotated `-> str`.
- C. Export `void *` for anything unannotated and rely on
  `_reconcile_imported_global_accessors` (`emit_infra.py` ~1989). Not
  recommended: a separate-compile extern then disagrees with the definer's
  `char *`, and int64 globals get pointer-typed reads, with no measure of either.

**Recommendation: B.** It reuses the existing mojo rule, so there is no second
inference. In-unit TUs stay exact through `_reconcile_imported_global_accessors`.

**Implementation plan (B):**
1. `module_loader.py:465`: annotate `_find_stdlib_path() -> str`.
2. `module_loader.py` `load_module_from_path`, `.py` branch (~1156-1222): after
   the set and container scans, add a column-0 scan for `NAME[: ann] = RHS`
   where `NAME` is not already exported. Type it by the rule in B, using the
   same `c_return_type` table as the mojo branch (~1385-1410). Leave the
   `_scan_container_literals` gate and the set-global path untouched.
3. Do not touch the stub skip at `module_gen.py` ~11154 (the accessor-map gate).
   The stub stays for any global whose accessor is unresolved.
4. `test_imported_global_stub.py`: add `owner.py` with `STRING_GLOBAL: str =
   _pick()` and `def _pick() -> str`, and a function-scoped
   `from owner import STRING_GLOBAL` in `types.py`. Assert on the
   `do_imports=False` compile of `types.py`: no `_funcptr_STRING_GLOBAL`, no
   `extern int64_t STRING_GLOBAL`, and `owner__mojo_global_get_STRING_GLOBAL`
   present. Confirm it is RED first: the current tree emits both
   `extern int64_t STRING_GLOBAL (...)` and `_funcptr_STRING_GLOBAL`.
   Check that `owner.py` resolves through `_local_sibling_module_exports` in the
   probe directory. It did not for the `str` global today, which is consistent
   with the scanner gap, but resolution itself is not yet confirmed.
5. Integrator gate for this change: `compile_stdlib.py` `skip` count and
   `U` must not rise. The stage1 closure dump must lose `STDLIB_PATH` from its
   weak definitions. Check for new `conflicting types` lines, since the
   scanner comment shows a broad export has broken `gimple_codegen`
   before. Only annotated `str`/`int`/`float` globals and callees with an
   annotated return are added, which is what makes this narrower than that
   attempt.

Quick test after landing: `python3 tools/memslot.py --gb 8 --label imported-global -- python3 test_imported_global_stub.py`.
