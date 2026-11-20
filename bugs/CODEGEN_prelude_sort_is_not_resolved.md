# CODEGEN: the prelude `sort` is not resolved without an explicit import

`sort` is a prelude name (`std/prelude/__init__.mojo:127`, `from std.builtin.sort import partition, sort`),
so Mojo code calls it with no import. `fire.py build` of

    def main() raises:
        var p = List(length=5, fill=Scalar[DType.int8](3))
        sort(p)
        print(len(p))

fails at link time with `Undefined symbols ... "_sort"`: the call lowers to a bare `sort` that nothing defines.
With `from std.builtin.sort import sort` it builds, but the call is the weak stub and prints
`sort: unavailable in compiled mode`, so the real `sort` is not compilable either.

Measured 2026-11-19. Found while landing the nested-bracket fix: `test/builtin/test_sort_issue_1018.mojo`
called it inside a generic and only failed `gcc -c` once that generic was really instantiated.
(That failure is gone: it was the instance not seeing its module's imports, a different defect.)

## What was tried

Adding `'sort': 'std.builtin.sort'` to `GimpleGen._PRELUDE_GENERICS` (the `alloc` mechanism,
`mojo/backend_gimple/emit_funcs.py::_register_imported_generics`) makes the call elaborate the real `sort`,
which then fails with `invalid conversion in gimple call` at `std/collections/counter.mojo:948` and
`invalid use of void expression` at the call. Reverted.

## Exact next step

1. Decide the contract: an unimported prelude `sort` should resolve exactly as the imported one (honest
   weak stub) until `std.builtin.sort` compiles. Make the unresolved bare name register that stub.
2. Then make `std.builtin.sort.sort` compile (the `counter.mojo:948` conversion and the `void`-used-as-value).
3. Test: the program above prints `5`, and `print(p[0])` after a sort of `[3, 1, 2]` prints `1`.

## Status 2026-11-20: step 1 landed; step 2 is still open

- The unresolved prelude `sort` no longer fails at link time. Its predeclared
  util stub (`_util_pairs` in `mojo/backend_gimple/module_gen.py`) is now the
  same honest weak definition the unknown-name path emits:
  `sort: unavailable in compiled mode`. The doc's program builds with
  `fire.py build` and runs, printing `sort: unavailable in compiled mode5` (the
  stub prints without a newline, as the unknown-name stub does) and then `5`.
- Gates: stdlib compile `FAILED: 0 (0 expected, 0 unexpected)` and the dylib
  `1203 of 1203` with no skips, both identical to master's.
- Not done: step 2 (make `std.builtin.sort.sort` compile, which is the
  `counter.mojo:948` conversion and the void-as-value). Step 3's `prints 5` /
  sorted-value test therefore does not hold yet, and this doc stays open.
