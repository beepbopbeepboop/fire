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

## Status

**2026-11-19 — step 1 landed (honest stub), step 2 open.** An unimported prelude `sort`
now builds and runs, lowering to the same honest weak definition an imported-but-not-yet-
compilable `sort` gets.

The root cause of the LINK failure was not the missing prelude model by itself: the
unknown-name path (`emit_calls.py::_lnc_unknown`) already emits a weak
`__attribute__((weak)) int64_t sort (...) { mojo_print("sort: unavailable in compiled mode"); ... }`
for a name nothing in the compile defines. But `module_gen.py`'s `_util_pairs` table also carried
`('sort', 'void sort(...);')`, which is emitted FIRST and DEFINES the shared `_MOJO_STUB_sort`
guard macro, so the weak definition (same guard) was `#ifndef`-skipped. The call site then bound
to the declaration-only `void sort(...)` and the link failed. Removing that one row (with the
reason recorded in its place) lets the existing weak definition stand. Every program that calls
the prelude `sort` without an import now gets the same answer as the imported spelling instead
of a linker error.

Pinned by `test_gimple.py::test_prelude_sort_without_import_is_an_honest_stub`: the program above
builds, runs, prints the stub message and `5`, and the generated C contains no
`void sort(...)` declaration-only stub. Verified additionally by gcc-linking and running the
emitted C directly. The one stdlib caller, `std/collections/counter.mojo` (`most_common`),
still single-unit compiles (`build_stdlib_dylib.compile_module_to_c`, 660086 bytes of C, 0.7 s)
and now carries the weak `sort` definition instead of the declaration-only stub.

**What remains (step 2) — the real `sort`.** Measured 2026-11-19 on this tree: with the
`_util_pairs` row removed AND `'sort': 'std.builtin.sort'` added to `GimpleGen._PRELUDE_GENERICS`,
the simple `sort(List)` call in the program above still falls through to the honest weak stub,
because elaboration declines: `sort` takes `Span[T, origin]` and the argument is a `List`. The
`Counter.most_common` site (`std/collections/counter.mojo:948`, `sort(items, comparator)`) has
the same `List` -> `Span` shape plus a nested comparator function value. So making the real
builtin work is not just "make std.builtin.sort compile": the call site needs the implicit
`List` -> `Span` conversion (and the comparator function value) before the elaborated generic
can be emitted at all. The earlier "invalid use of void expression" in this doc was another
symptom of the `_util_pairs` row (the `void` declaration was the one the call bound to), not a
separate return-type bug: with the row removed the call no longer reaches a `void` declaration.

## What was tried

Adding `'sort': 'std.builtin.sort'` to `GimpleGen._PRELUDE_GENERICS` (the `alloc` mechanism,
`mojo/backend_gimple/emit_funcs.py::_register_imported_generics`) makes the call elaborate the real `sort`,
which then fails with `invalid conversion in gimple call` at `std/collections/counter.mojo:948` and
`invalid use of void expression` at the call. Reverted. (The `void` half is fixed by the 2026-11-19
`_util_pairs` change; the `List` -> `Span` conversion is still missing.)

## Exact next step

1. ~~Decide the contract: an unimported prelude `sort` should resolve exactly as the imported one (honest
   weak stub) until `std.builtin.sort` compiles. Make the unresolved bare name register that stub.~~
   Done 2026-11-19 (see Status).
2. Then make `std.builtin.sort.sort` compile. The call site must first turn its `List` argument into
   the `Span` the generic takes (`counter.mojo:948` is the same shape), which is the missing piece
   measured above; the generic body's own `counter.mojo` conversion then has to compile as well.
3. Test: the program above prints `5`, and `print(p[0])` after a sort of `[3, 1, 2]` prints `1`.

## Done when

`test_gimple.py::test_prelude_sort_without_import_is_an_honest_stub` passes (the step-1 contract,
landed 2026-11-19), and a test next to it builds and runs

    def main() raises:
        var p = List(length=3, fill=0)
        p[0] = 3
        p[1] = 1
        p[2] = 2
        sort(p)
        print(p[0])

with stdout exactly `1` and no `unavailable in compiled mode` — that is step 2, still open.
