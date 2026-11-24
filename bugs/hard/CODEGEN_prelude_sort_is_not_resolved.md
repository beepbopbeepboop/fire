SPLIT: CODEGEN_prelude_sort_is_not_resolved-part1, CODEGEN_prelude_sort_is_not_resolved-part2, CODEGEN_prelude_sort_is_not_resolved-part3, CODEGEN_prelude_sort_is_not_resolved-part4, CODEGEN_prelude_sort_is_not_resolved-part5, CODEGEN_prelude_sort_is_not_resolved-part6, CODEGEN_prelude_sort_is_not_resolved-part7

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

**2026-11-20 (round 5) — container projection landed: `_quicksort`'s helper chain now elaborates; Span runtime methods are the open gap.**

- *Step 1 of the recorded next step landed.* `emit_resolve._proven_local_types`
  generalizes the round-4 `_proven_list_locals` and proves a local's Mojo type
  from: a `List[X]`/`Span[X, o]` annotation, a `List[X](...)` constructor's own
  bracket (`_list_ctor_mojo_type`, balanced nested args), a
  `List(length=, fill=)` literal, and a ONE-STEP projection — `.pop()` or a
  non-slice subscript — out of a proven `List[X]`/`Span[X, o]`
  (`_projection_type`/`_container_elem_type`). Exactly-once-binding and
  in-place-store rules are unchanged. `_proven_span_arg_mojo_type` is the
  `Span *` argument proof (local, enclosing parameter, or the projection
  expression itself), and `_unify_param_ann` accepts it from a BOXED
  `int64_t` slot as well as from `Span *`: `List[Span[T, origin]].pop()`
  lowers to an `int64_t` word, but the word IS a Span header.
- *Call-site half.* `_coerce_span_args` casts a proven boxed `int64_t` to
  `Span *` (`span_proofs` from the call's own arguments; an unproved
  `int64_t` keeps the old ABI/diagnostic). Its `MojoList *` conversion now
  reads `data`/`len` into temps before the span store: `gcc -fgimple`
  rejects a `component_ref` there ("invalid RHS for gimple memory store")
  and a cast over one ("invalid operand in unary operation"), measured on
  `std.collections.counter`'s `sort(items, comparator)` once the prelude
  elaboration reaches it.
- *Measured.* std.builtin.sort's `_quicksort[Int64, MutOrigin,
  do_smallsort=False]` instance now builds **8** nested helper objects (was
  4) and emits real calls `_insertion_sort_...`, `_sort3_...`,
  `_quicksort_partition_left_...`, `_quicksort_partition_right_...`; the bare
  stubs for those four are gone from its C. Weak stubs left per helper:
  `_insertion_sort` -> `Span_as_ref`; `_sort2`/partition_left/right ->
  `Span_unsafe_get` + `Span_unsafe_swap_elements`; `_quicksort` ->
  `Span_unsafe_ptr`. With the prelude `sort` temporarily registered,
  `std.collections.counter`'s single-unit C (668885 bytes) now passes
  `gcc -fgimple -fsyntax-only`; `sort` is still NOT registered, so the
  Done-when program still prints the honest stub.
- *Tests.* New `test_proven_span_local_from_a_list_projection` (fails at HEAD:
  no `_proven_local_types`; passes now), new
  `test_boxed_span_arg_is_cast_to_a_span_only_when_proven` (proof-gated cast,
  and the component-ref-free span conversion), and
  `test_span_param_binds_from_a_proven_span` extended with boxed
  `int64_t` cases (first case fails at HEAD). Full `test_gimple.py`:
  **469 passed, 0 failed**.

**Next step (step 2, measured blockers in order).** A `Span[X, o]` PARAMETER
annotation is never materialized as a generic struct: `_materialize_generic_
struct_mentions` is called for FIELD and RETURN annotations only
(`emit_resolve.py` ~4211/4227), so the helper instances keep the builtin
`Span` stub and their method calls stay weak stubs. Making
`_ensure_generic_struct('Span', ['Int64', 'MutOrigin'])` work first needs
four generic-STRUCT binder defects fixed (all measured on
`std/collections/span.mojo`):

1. `elaborate.type_param_defaults` splits `origin: Origin[mut=mut]` at the
   `=` INSIDE the brackets, so `origin`'s default reads `mut]` and
   `_default_type_arg` rejects it — split at a top-level `=` only.
2. `address_space: AddressSpace = .GENERIC` has no value default:
   `_default_type_arg('.GENERIC')` returns None — render the enum-value
   default (`.GENERIC` -> `GENERIC`) or accept it as a comptime value.
3. `bind_type_args` treats the deduced prefix before `//` positionally:
   `Span` is `Span[mut: Bool, //, T, AnyType, origin, *, address_space]`, and
   the stdlib spells it `Span[T, origin]`, so `mut` must be deduced
   (`MutOrigin` -> `True`) and `address_space` defaulted, as
   `complete_explicit_type_args` already does for function calls.
4. `monomorphize._check_no_value_shadow` reads the keyword label
   `address_space=Self.address_space` (span.mojo:859, inside a `Pointer[...]`
   bracket) as an assignment binding, because only `{}` depth is excused —
   excise labels inside any bracket/paren, not only braces.

With (4) monkeypatched and all four args supplied
(`['True','Int64','MutOrigin','GENERIC']`), `Elaborator.elaborate_generic_struct
('span.mojo','Span',...)` succeeds in ~0.7 s and lists `as_ref`,
`unsafe_ptr`, `unsafe_get`, `unsafe_swap_elements` (and the rest), so the
struct itself is ready; the binder + parameter-annotation hook is what is
missing. Then (3) module comptime constants in isolated TUs
(`insertion_sort_threshold` still erases to `(int64_t)0`), and only then
register `sort`.

**2026-11-20 (round 4) — steps 2a/2b landed and measured; stop condition invoked; `sort` NOT registered.**

- *2a landed (with a round-3 draft defect fixed).* `emit_resolve.py::_proven_list_locals(gen)` maps a
  local bound exactly once by `var p: List[X]` / `var p = List(length=n, fill=<literal>)` to `'List[X]'`,
  and — the round-3 draft's defect — an in-place store (`p[0] = 3`) must NOT end the proof: the draft
  counted subscript targets as bindings (`gex._names_bound_by` over-counts), so `p` in the Done-when
  program was never proven. `_bare_name_target_names` counts only bare/tuple targets as rebinds.
  Pinned by `test_proven_list_local_keeps_element_type_across_inplace_store` (fails at HEAD:
  `AttributeError: no attribute '_proven_list_locals'`; passes now).
- *2b landed.* `_coerce_span_args` in `_emit_generic_instantiation`: a `MojoList *` argument whose
  instance parameter is `Span *` becomes a fresh `_alloc_Span` over the list's own storage
  (`_data = (char*) list->data; _len = list->len`). One helper for every `Span` parameter.
- *Chain fixes 3-5 landed.* (3) the inferred arm passes
  `generic_paths=_generic_paths_with_module(gen, source, module_src)` (the callee module's own generic
  functions, so the instance's sibling calls elaborate); (4) `elaborate.py::_unify_param_ann` binds
  `Span[T, o]` <- a PROVEN `Span[X, o]` argument (the nested chain passes the same proven Span down),
  guarded by `_is_concrete_type_arg` + concrete-origin agreement — a still-generic proof binds nothing;
  (5) bare-sibling routing: the `_gen` gate in `emit_calls._lower_call`, the ExprStmt fast path in
  `emit_stmts._gen_stmt_ExprStmt`, and the source lookup in `emit_resolve._elaborate_generic_call`
  accept BARE sibling-map names (statement-position `_insertion_sort(interval, cmp_fn)` in the `_sort`
  instance fell to the weak stub before). Pinned by `test_span_param_binds_from_a_proven_span`
  (fails at HEAD: proven Span declined) and `test_arity_overloads_mangle_to_distinct_symbols`.
- *Mangle injectivity defect found and fixed (shared, arity-keyed).* The two `sort` overloads
  (`sort(span)` / `sort(span, cmp_fn)`, same type-param names) mangled to ONE symbol for the same type
  args; the moment the 1-arg instance's own body call elaborated the 2-arg overload, the 1-arg TU
  declared the 2-arg extern beside its own definition and gcc failed "too many arguments".
  `elaborate.py::_arity_overload_clash` + `targs['ArgC'] = arg_count` (same mechanism as the variadic
  fold): `sort_4_ArgC_1_1_...` vs `sort_4_ArgC_1_2_...`. Disambiguation is by ARITY, never by name.
- *Bare-sibling gate regression found and fixed this round.* The bare-sibling additions above let the
  `sin_5_...` instance's OWN body (built in its isolated TU) elaborate its comptime-dead narrowing arm
  `comptime if size_of[dtype]() < size_of[.float32](): return sin(...)` — a BARE SELF-call that now
  resolved through the sibling map and raised the self-recursion refusal, breaking the pre-existing
  `gate_stdlib_syntax_imported_generic_bracket_args` gate (passed at HEAD, where the bare gate checked
  `_imported_generics` only and the self-call stubbed in its dead branch). Fix: the bare-sibling branch
  of the `_gen` gate excludes a call whose name self-references `current_func_name`
  (`name == cfn or cfn.startswith(name + '_')`, the existing `self_recursive_uninstantiable`
  convention). Bare self-calls keep exactly the HEAD stub; bracketed self-calls and true siblings
  (different names) are untouched. Measured: the gate's probe compiles again; the sort chain still
  elaborates all 4 nested helper objects.
- *New regression tests verified fail-before/pass-after.* All three new tests FAIL at HEAD
  (`3 of 3 failed at HEAD`) and PASS on the fixed tree; full `test_gimple.py`: **469 passed, 0 failed**.
- *Measured failing helper (the recorded one).* In the `_quicksort` instance TU the bare calls
  `_insertion_sort(interval, cmp_fn)`, `_sort3(interval, len >> 1, 0, len - 1, cmp_fn)`,
  `_quicksort_partition_left/right(interval, cmp_fn)` are DECLINED because `interval` is the `Span *`
  local from `stack.pop()` on a `List[Span[Int, MutOrigin]]`: proving the element type needs the
  container's element type, and the current proof covers only (a) the enclosing function's own
  parameter annotation, (b) a `List(length=, fill=)` constructor at the call site, (c) a proven List
  local — not a one-step projection from a proven List's `.pop()`.
- *Deeper measured gaps (why the instance still cannot run).* (1) The Span runtime API
  (`as_ref`, `unsafe_offset`, `unsafe_take_pointee`, `unsafe_write(_move_from)`, `unsafe_get`,
  `unsafe_swap_elements`, `unsafe_subspan`, `unsafe_ptr`) is weak no-op stubs inside the helper
  instances: the `_insertion_sort[Int, MutOrigin]` object builds with a real loop, but `as_ref` prints
  a message and returns 0. (2) The module comptime constant `insertion_sort_threshold` erases to
  `(int64_t)0 /* ct param or undeclared */` in the isolated TU, so the `len < 32` small-sort branch is
  dead. Both are features larger than Span/List per the stop condition.
- **Stop condition invoked (per the plan): `sort` is NOT added to `_PRELUDE_GENERICS`; the Done-when
  program prints the honest stub, which is correct while the instance cannot run.**

**Exact next step (in order):** (1) container-projection proof — a proven `List[X]` local's
`stack.pop()`/index yields a proven `X` argument (one step; the recorded failing helper);
(2) the Span runtime methods in helper instance bodies (their shared gap, per the plan's step 3:
fix each by its own doc'd gap, no sort special-casing); (3) module comptime constants in isolated TUs
(`insertion_sort_threshold`); (4) re-measure the Done-when program, and only then register `sort`.

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
   the element-type proof for a local `List` AND the `List`/boxed-`Span` call-site
   conversion (step 1 of the round-4 next-step list) landed in round 5 — see
   Status. `counter.mojo:948`'s conversion now emits GIMPLE-clean C.) The
   remaining open piece is step 2 of that list: the Span runtime methods inside
   the helper instances, blocked on materializing a `Span[X, o]` parameter
   annotation as a generic struct (the four binder defects are measured in
   Status).
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

## Status 2026-11-20 (second round): measured blockers for step 2, in order

Measured on master with `fire.py build` (link mode):

1. **An explicit import does not instantiate the generic.** `from std.builtin.sort
   import sort` + `sort(span)` builds and runs, and prints the weak stub, so the
   real `sort[...]` is never elaborated for an imported generic. Only the
   `_PRELUDE_GENERICS` path tries (`alloc` works that way). The first
   instantiation step is to make the import of a generic function register it for
   elaboration at the call, the way `_register_imported_generics` already does for
   the prelude table.
2. **Elaborating `sort` with the prelude table set fails in the stdlib, not at the
   call.** `std/collections/counter.mojo:948` (`sort(items, comparator)`, a nested
   `def` passed as the `Some[def(T, T) -> Bool]` argument) gives `invalid conversion
   in gimple call`. The call site in the user program gives `invalid use of void
   expression`. A user-defined generic that returns nothing (`def bump[T](mut x: T)`)
   builds and runs, so the void error is specific to the elaborated `sort`
   (overload choice between the two `sort` overloads, or the instance's return type).
3. **`sort(p)` with a `List` needs an implicit `List` -> `Span` conversion**, which
   the compiler does not perform for a generic argument. With an explicit `Span(p)`
   the call type-checks; the conversion is a separate step.
4. **`List[Int](3, 1, 2)` (variadic constructor) builds and then fails at run time
   with `IndexError: list index out of range`.** Separate from `sort`; it blocks
   writing step 3's test with a literal list, so the test uses `List(length=, fill=)`
   and item assignment for now.

Next round, in this order: (1) make an imported generic function elaborate at its
call site, measured on `sort(sp)` with an explicit `Span`; (2) fix the nested-`def`
argument conversion that `counter.mojo:948` hits; (3) the void-as-value of the
elaborated instance; (4) the `List` -> `Span` implicit conversion; (5) step 3's
test. Each step has its own program above; the bug stays open until (5) passes.

## Status 2026-11-20: the unconditional stub now reaches the closure gate (measured)

- Every `--dump-full` artifact now carries the prelude `sort` stub, whether or not
  the program mentions `sort`. A one-line program (`def f(n): return n + 1` +
  `print(f(1))`) dumps `prog.ci` with `_util_pairs`'s `sort(...)` weak stub at
  line 308 (`sort: unavailable in compiled mode`).
- That matters because master's `--dump-full` (commit 5468c8f80, "reports the
  weak stubs its .ci carries") prints `closure: <name>.ci carries an unavailable
  in compiled mode stub` on that artifact. The line contains the phrase that
  `tools/suite.py`'s `CLOSURE_INCOMPLETE` rejects, so `bootstrap-stage1-transitive`,
  `bootstrap-stage2-transitive` and `bootstrap-stage3-transitive` reject their
  output on master. Not gated yet: this was measured with the quick fixture only,
  not a bootstrap run.
- `test_dump_full_reports_closure_stubs.py` on master: `test_stub_in_artifact_is_reported`
  passes; `test_clean_artifact_is_quiet` fails on the `assert PHASE not in ci`
  line, for the reason above. The test's premise (a program with no stub) is no
  longer true until this bug's stub goes away.
- Consequence for this doc's plan: step 2 (a real `std.builtin.sort.sort`) is what
  clears it. An interim choice is open for the controller: emit the predeclared
  stub only when `sort` is referenced, which clears the closure gate sooner and
  is a separate decision from step 2.
