# CODEGEN_peekable_iterator_methods_not_emitted

## Summary
On master (2026-11-11) every compiled program fails at load: `dyld: symbol not found in flat namespace
'_std_iter___init____PeekableIterator_peek'`. The cause is the stdlib dylib. `build/libmojostdlib.arm64.dylib`
REFERENCES `_std_iter___init____PeekableIterator_peek` (`nm -u`) but does not DEFINE it (`nm -gU`), and it
also lacks `_PeekableIterator.__next__`. The methods are defined in `std/iter/__init__.mojo` (`_PeekableIterator`,
line ~766; `peek`, line ~813). Nothing else in the stdlib calls `peek`.

## Evidence
- A trivial program (`def main(): print(7)`) builds (`fire.py build`) and aborts at load on master and on the
  merged round-31 tree alike, so the cause is not the class-rebind work.
- Rebuilding master's `stdlib-dylib` job produces the same 4,996,808-byte dylib with no `peek`.
- The old `build/libmojostdlib.dylib` (Sep 27) does define `peek` and `__next__`, but it was not produced by the
  current `stdlib-dylib` job, so it is not a baseline.
- The `stdlib-dylib` job exits 1 on master for an unrelated reason (see `CODEGEN_simd_math_call_violated_constraint`)
  and does NOT list `std/iter` in its skips, so the missing methods are silent. See `SUITE_stdlib_dylib_missing_exports_silent`.

## Repro
```
def main():
    print(7)
```
`python3 fire.py build t.mojo -o t.bin && ./t.bin` prints `7` when the stdlib dylib is right; on master it aborts.

## Status
Open. The likely area is generic-struct elaboration: `_PeekableIterator[InnerIterator]` is a parameterised
struct whose methods are referenced but never instantiated. Not started.

## Done when
`./t.bin` prints `7` from a clean `build/`, AND `nm -gU build/libmojostdlib.arm64.dylib` defines
`_std_iter___init____PeekableIterator_peek` and `..._next__`. Then delete this doc in the same commit.
