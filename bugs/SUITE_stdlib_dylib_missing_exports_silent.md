# SUITE_stdlib_dylib_missing_exports_silent

## Summary
`stdlib-dylib` passes (or fails only for unrelated reasons) while the stdlib dylib it builds references symbols
it never defines. Master's `build/libmojostdlib.arm64.dylib` references
`_std_iter___init____PeekableIterator_peek` (`nm -u`) but does not define it (`nm -gU`), so every compiled
program aborts at load. The job did not report it.

## Evidence
- `stdlib-dylib` on master: `NEW dylib skips` lists only the six `invalid call` stdlib files, nothing from `std/iter`.
- The tree already has the tools to catch this: `tools/undef_import_census.py` and `tools/linkcheck.py` both read
  the arm64 dylib. `stdlib-dylib` does not run an undefined-reference check on its output.

## Repro
`python3 tools/suite.py stdlib-dylib`, then `nm -u build/libmojostdlib.arm64.dylib | grep PeekableIterator_peek`.
That prints the reference, and the job still reports only the skip list.

## Status
Open. Not started. The gate gap, not the missing methods themselves (those are `CODEGEN_peekable_iterator_methods_not_emitted`).

## Done when
`stdlib-dylib` FAILS when the built dylib has an undefined reference into the stdlib (a `_std_` symbol referenced
but not defined), with a test that proves it catches `_PeekableIterator_peek`. Then delete this doc in the same commit.
