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

## Investigation (2026-11-11), mechanism found
- The reference is in the runtime class table, not in user code. `__mojo_register_classes` and
  `__mojo_classattr_read` load the GOT slot for `_std_iter___init____PeekableIterator_peek` (`dyld_info -fixups`
  shows two binds; `llvm-objdump -d` shows the `adrp`/`ldr` in those two functions).
- The table is emitted in `mojo/backend_gimple/module_gen.py` (around lines 18517-18570): for every static struct,
  each non-dunder method gets `mojo_class_setattr(tag, "<name>", &<csym>)`, whether or not its body is emitted.
- In the arm64 dylib, `_PeekableIterator`'s non-dunder methods are `init`, `iter`, `bounds` (defined) and `peek`
  (table entry only). `__next__` is a dunder, so it has no table entry, and its body is also absent.
- So the body of `peek` (and `__next__`) is dropped somewhere in method emission while the table still names it.
  Hypothesis, not yet checked: the drop is caused by the return type
  `Optional[Pointer[Self.Element, ImmOrigin(origin_of(self._next[]))]]`, which carries an origin.
- Next step: find where `peek`'s body is dropped in the emitter (start from the methods of a generic struct whose
  return type is an origin-parametrised `Pointer`), write a user-level repro with the same shape, and make the body
  emit. Do NOT fix this by skipping table entries for missing bodies: that hides the drop.

## Status
Open. The likely area is generic-struct elaboration: `_PeekableIterator[InnerIterator]` is a parameterised
struct whose methods are referenced but never instantiated. Not started.

## Done when
`./t.bin` prints `7` from a clean `build/`, AND `nm -gU build/libmojostdlib.arm64.dylib` defines
`_std_iter___init____PeekableIterator_peek` and `..._next__`. Then delete this doc in the same commit.
