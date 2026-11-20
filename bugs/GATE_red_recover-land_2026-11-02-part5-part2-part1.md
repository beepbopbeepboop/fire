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
