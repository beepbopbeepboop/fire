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

**2026-11-19 (round 3) — step 2a/2b designed and drafted, NOT landed; end-to-end unmeasured.**
Drafted and checked (unit level only) the two pieces the planning guide below asks for, then
reverted them because the end-to-end measurement did not finish in this round:

- *2a, element type of a local.* `emit_resolve.py`: a per-body cache `_proven_list_locals(gen)` maps
  a local bound exactly once (`gex._names_bound_by` count == 1) by `var p: List[X]` or
  `var p = List(length=n, fill=<literal>)` to `'List[X]'` (`_literal_mojo_type`, so `0` is `Int`);
  `_proven_arg_mojo_type`'s IdentExpr branch falls back to it after the parameter check.
- *2b, Span conversion.* `emit_resolve.py::_coerce_span_args(gen, info['params'], arg_pairs)`, called
  in `_emit_generic_instantiation` after the arity truncation: a `MojoList *` argument whose instance
  parameter is `Span *` becomes a fresh `_alloc_Span` with `_data = (char*) list->data`,
  `_len = list->len`. One helper for every Span parameter.
- *Inferred path.* `_elaborate_generic_call` passes `_inferred_arg_mojo_type` (proven type for a
  `MojoList *` argument only; literal inference unchanged).
- *Guard.* `elaborate.py::_unify_param_ann`: a proven `List[X]` declines the bare `x: T` shape, so
  only the Span shape sees the new proof (pinned by an added assertion in
  `test_span_param_binds_only_from_a_proven_list`, which passes).

Measured: the Done-when program still prints the honest stub (no registration yet; expected). The
`from std.builtin.sort import sort` variant was run once under the 8 GB cap and did not finish in
~12 minutes (RSS climbed to ~1 GB, then the background run was stopped by the harness), so whether
the real sort now elaborates, and what it fails on, is NOT known. The drafted diff was saved only in
the worktree's git-ignored `.tmp/`, not committed; re-derive from the description above.

**Next step for the next round:** re-apply 2a/2b, then measure the imported program as a
single-unit `elaborate_generic_call` of `std.builtin.sort.sort` (not a whole-closure program run),
to find the first failing helper before touching `_PRELUDE_GENERICS`.

**2026-11-20 — planning step 1 landed (`Span[T, o]` <- `List[X]` unify rule); step 2 blocked on a
proof this lane does not yet have.** `elaborate.py::_unify_param_ann` now binds a `Span[T, o]`
annotation from a `MojoList *` argument, but ONLY when the caller proves the list's Mojo type
(`arg_mojo == 'List[X]'`): `T := X`, and `o := ERASED_TYPE_ARG` (`MutOrigin`). Without that proof,
or for a `Pointer` argument, it still declines. Pinned by `test_gimple.py::test_span_param_binds_only_from_a_proven_list`
(fails before the change: `infer_type_args` returns None for the proven List; passes after).
The honest-stub test and `test_inferred_generic_statement_call.py` still pass.

**Why step 2 did NOT land.** The Done-when program's `p` is `List(length=3, fill=0)` with no
annotation. `_proven_arg_mojo_type` (`emit_resolve.py:3574`) proves a type only for a literal, a
direct constructor call, or a parameter of the enclosing function. A local `var p = List(...)` has
no recorded element type, so the call still declines and the elaborator never sees the Span
binding. Step 2's `MojoList * -> Span *` conversion in `_elaborate_generic_call` would therefore be
dead code today, and untestable against the Done-when program, so it was not landed.
**Next step for step 2 (ordered):** (a) record the Mojo element type of a local bound to a
`List(...)` constructor (from `fill=`'s proven type, or an explicit `List[X]` annotation) in the
same place parameters are recorded for `_proven_arg_mojo_type`; (b) only then add the
`MojoList * -> Span *` helper and its call in `_elaborate_generic_call`; (c) steps 3-4 of the plan.

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

**2026-11-19 — planning round for step 2 (the real `sort`).** Step 2 is a feature, not a one-line
registration. Everything below was established by reading the code; nothing in it has been
changed or run beyond the measurement above. The next round can start at item 1 without
re-investigating.

*Where the real sort lives.* The stdlib is the external checkout
`/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib` (not in this worktree; `module_loader.py`
~line 450 searches it). The file is `std/builtin/sort.mojo`, with two public overloads:

- line 485: `def sort[T: Copyable, origin: MutOrigin, //, *, stable: Bool = False](span: Span[T, origin], cmp_fn: Some[def(T, T) -> Bool])`
- line 530: `def sort[T: Copyable & Comparable, origin: MutOrigin, //, *, stable: Bool = False](span: Span[T, origin])`

Both delegate to the private helpers `_insertion_sort` (34), `_quicksort_partition_right/left`
(61/89), `_heap_sort_fix_down`/`_heap_sort` (114/136), `_delegate_small_sort` (164), `_quicksort`
(194). `partition` (434) has the same `Span`/`Some[def]` shape.

*Where the current path stops, by code.*

- `elaborate.py::_unify_param_ann` (3066) binds a parameter only when the annotation IS the type
  parameter, or is `Scalar[..]`/`SIMD[..]`. `Span[T, origin]` is neither, so it returns `{}`
  and `infer_type_args` (3492) declines the call. That is the "declined" half of the failure.
- `mojo/backend_gimple/emit_resolve.py::_elaborate_generic_call` (3630) lowers the arguments and
  hands their C types to the elaborator. A `List` argument arrives as `MojoList *`; the callee
  expects a runtime `Span *` (the ctype is already known: emit_resolve.py:3561 lists `Span *`).
  Nothing converts one into the other, so even a bound instance would be passed the wrong ABI.
- `Some[def(T, T) -> Bool]` (the `cmp_fn` parameter) is not an annotation shape that
  `_unify_param_ann` handles either. The one-argument overload (530) avoids it, so the
  simple `sort(p)` call needs the `Span` work only.
- `gimple_codegen.py:4574` `_PRELUDE_GENERICS = {'alloc': 'std.memory.unsafe_pointer'}` is the
  registration step 2 adds `'sort': 'std.builtin.sort'` to. Done alone it reproduces the
  measured "invalid conversion in gimple call" / "invalid use of void expression" failure.
- `elaborate.extract_fn_source(module_src, g, arg_count=...)` already selects by arity, so the
  two overloads are distinguishable once the `Span` binding exists.

*Decisions needed, with a recommendation for each.*

1. **Where the List->Span conversion lives.** (a) In the elaborator, teaching `_unify_param_ann`
   the shape `Span[T, o]` <- `List[X]` (binding `T := X` from the list element type and `o` to
   the erased origin) plus a call-site conversion in `_elaborate_generic_call`; or (b) rewrite the
   call site before elaboration into `sort(Span(p))`-style source. **Recommend (a).** (b) would
   special-case one spelling and leave `Counter.most_common` (`std/collections/counter.mojo:948`,
   `sort(items, comparator)`) on the old path. The conversion must be one function that every
   `Span`-taking generic call uses, not a `sort`-only branch.
2. **Which overload a bare `sort(p)` selects.** Recommend arity selection through
   `extract_fn_source(..., arg_count=1)`, which is already there. Do NOT special-case the name.
3. **The comparator.** The one-argument overload needs only `T: Comparable`, so step 2's test
   does not need `Some[def]`. `Some[def(T, T) -> Bool]` for `Counter.most_common` is a separate,
   later decision (its own unify rule for a function-value argument); record it, do not fold it in.

*Implementation plan, in order.*

1. `elaborate.py::_unify_param_ann`: add the `Span[T, o]` <- `List[X]` case beside the
   `Scalar`/`SIMD` cases, returning `{T: X, o: <erased origin>}`. Reject the shape (return `{}`)
   for any other argument, so a `Span` parameter given a `Pointer` still declines. Unit test:
   `infer_type_args` on `Span[T, origin]` with a `List[Int8]` argument binds `T = Int8` and does
   not bind a `Pointer` argument.
2. `emit_resolve.py::_elaborate_generic_call`: when a parameter's annotation is `Span[...]` and the
   argument's C type is `MojoList *`, emit a `Span` from the list's data pointer and length
   (the same runtime struct `Span *` already uses) and pass that. One helper, reused by any
   future `Span` parameter.
3. Make the instance compile: `_quicksort`, `_insertion_sort`, `_delegate_small_sort` use
   `comptime` constants and `Span` subscripts/`swap`. Measure which of them fail after steps
   1-2 (a single-unit compile of the instance, not a stdlib sweep) and fix each by its own
   doc'd gap, not by special-casing `sort`.
4. `gimple_codegen.py:4574`: add `'sort': 'std.builtin.sort'` to `_PRELUDE_GENERICS`. Only now
   does the bare name elaborate the real sort instead of the stub.
5. Quick tests (the only gate this lane runs): the `infer_type_args` unit test from step 1, and
   the Done-when program below. `test_gimple.py` next to `test_prelude_sort_without_import_is_an_honest_stub`.

*Stop condition for step 2.* If step 3 shows the helper chain needs a feature larger than
`Span`/`List` (for example the `Some[def]` comparator on the 1-arg path, or `origin` parameters
that the elaborator cannot erase), land steps 1-2 with their unit test and record the exact
failing helper here. Do not register `sort` in `_PRELUDE_GENERICS` until the instance compiles,
or the stub becomes a silent miscompile instead of an honest one.

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
2. Then make `std.builtin.sort.sort` compile. (Step 1 of the planning guide, the unify rule, is landed;
   the element-type proof for a local `List` is the open piece, see Status.) The call site must first turn its `List` argument into
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
