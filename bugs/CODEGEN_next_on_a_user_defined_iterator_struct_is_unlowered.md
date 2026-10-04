# `next(<user-defined iterator struct>)` has no lowering, and the callee's
# type is not inferred either

## Status

OPEN. The receiver's TYPE-INFERENCE half is unchanged and is still parked —
see "What the remaining blocker actually is" for the three measurements of it.
Everything else this doc once described as open has been settled, on either
side of the 2026-10-03 merge of the parallel tree, and none of the four claims
below had a test when it was written:

* `next(<a user-defined iterator struct>)` compiles and RUNS correctly whenever
  the receiver's type is resolvable. `def c = Counter(5, 8); print(next(c))`
  prints `5`, `6` on both pipelines against CPython's `5`, `6` — nothing
  undefined, nothing stubbed. The doc claimed this in "What is fixed" but
  nothing asserted it, so the half that works could have rotted into the same
  silence as the half that does not. It is now
  `test_gimple.py::test_next_on_a_user_struct_lowers_and_its_for_loop_says_why_not`,
  whose fixture also pins the `__iter__`-returning-self shape.
* The `for` loop over the SAME object — a struct with `__next__` and no
  `__has_next__` — emitted `cond = 0` with a `/* TODO: no __has_next__ */`
  marker: the body runs zero times, silently, exit 0. It now calls the same
  `mojo_unsupported_iter` every other unsupported iterable gets, so the
  diagnostic names the type, the reason and the loop's file:line:

      mojo_unsupported_iter: 'for' loop over unsupported iterable type
      nextstruct.py:18: Counter (no __has_next__) (codegen has no lowering
      for this container/iterator shape; the loop body runs zero times)

  The BEHAVIOUR is deliberately unchanged. Python's `__next__` signals
  exhaustion by RAISING, and the compiled raise is `mojo_exc_type_set (...)` +
  `mojo_raise ()` — verified in the generated `Counter___next__` — which unwinds
  past the loop with nothing left for a condition to test. There is no
  expressible loop condition, so the only honest options are "say so" (taken)
  and "invent a wrong loop" (rejected, and what "What the remaining blocker
  actually is" already rules out).
* The CROSS-MODULE half, which was not this doc's subject and had been hiding
  behind the type-inference gap: a user-defined iterator struct reached through
  `from mod import Struct` spelled its protocol methods' C names with a
  hand-written `{Struct}___{method}__` f-string instead of
  `gen._struct_method_csym`, the tree's one composer, so the home-module
  qualifier was dropped and the call went to a symbol nothing defines.
  `emit_loops._gen_for_struct_iter` (all three of `__iter__`, `__has_next__`,
  `__next__`) and `_lower_call`'s `next(<struct>)` branch both did this; both
  now compose through `gen._struct_method_csym`.

  Measured, on a two-module fixture (`xmoditer_defn.py` holding the struct +
  `make()`, `xmoditer_use.py` doing `next(d)` / `for x in d` / `next(e)`):

      before —
        error: implicit declaration of function 'It___next__'; did you mean 'itmod_It___next__'?
        error: implicit declaration of function 'It___iter__'; did you mean 'itmod_It___iter__'?
        error: assignment to 'It *' from 'int' makes pointer from integer without a cast
      after — builds clean and prints `1 2 3 1`

  Note the severity: gcc's `-Wimplicit-function-declaration` fallback types the
  undeclared call as returning `int`, so `It___iter__(It *)` became an `int`
  that was then assigned to an `It *` — a wrong pointer, not merely a missing
  symbol. So this was never going to stay a clean link error. Its regression is
  `test_gimple_runner.py::cross_module_iterator_struct_protocol_symbols`, which
  asserts the built binary's real stdout and that gcc is clean; pre-fix it does
  not compile at all. There is deliberately NO CPython comparison in that test:
  `__has_next__` is a Mojo-only protocol, so CPython has no such method and
  would call `__next__` until it raised — running the fixture under CPython
  loops forever.

None of that makes the 19 files build. They fail at the type-inference gap,
which is upstream of all of it.

### OPEN, and smaller: 19 files, down from 22

Three genuinely went green — `test/iter/test_empty.mojo`,
`test/iter/test_once.mojo`, `test/itertools/test_repeat.mojo` — and are out of
`EXPECTED_FAILURES` with per-file artifact evidence (below).
`undef_import_census` is **96 / 51 / 60, UNCHANGED**, and that is the honest
reading rather than a null result: the census only counts files that COMPILE,
and these three did not before, so there was never a census row to remove. The
census will not move until the remaining 19 do.

**2026-10-03: item 1 below (`test_count.mojo`) is BUILT, compiles all 592
files with 0 unexpected, and was REVERTED because its artifact links to
nothing.** It is a four-edit change to a real defect — a wrong signature, not
a missed optimization — and it is blocked BEHIND items 2 and 3, because
`std/itertools/itertools.mojo` does not compile at all, so `count` and
`_CountIterator.__next__` exist in no object. The full measurement, the
per-side `nm -g` evidence, both blockers, and the reusable findings are in
item 1. `test_count.mojo` therefore REMAINS in `EXPECTED_FAILURES` and the
sweep is unchanged at **591 / 19 / 0, exit 0**.

### ROUND 4 (2026-10-03): shapes 2 and 3 are mis-diagnosed, one of them is
fixable, and the acceptance bar in the plan is met by nothing

Three measurements. Two of them contradict the shape analysis below, which is
why they come first; the third is about the bar itself and it is the reason
this session landed a census section instead of a fix.

#### (a) Shape 2 is NOT a wrong pointer. All three C types are deliberate.

The claim under test was that "`var it = enumerate(...)` types `it` as
`MojoList *`: the erasure picked a container for an argument it could not
resolve". Measured, per type:

| observed | what actually produces it | verdict |
|---|---|---|
| `MojoList *` | `emit_calls._lower_call:2188-2190` routes a VALUE-position `enumerate(x)` to `_lower_builtin_enumerate_value` (`emit_calls.py:3751`), which **eagerly materialises** the `(index, element)` pair-lists into a `MojoList` and returns `'MojoList *'`; `mojo/middle/types.py:317` declares the same. The generated C is a real loop appending `mojo_list_new ()` pairs. | INTENDED, and correct for what it covers (`list(enumerate(x))`, `len(it)`, `it[i]` — the docstring records that the earlier identity and comprehension routes were both wrong) |
| `void *` | `_lower_builtin_zip_n` (`emit_calls.py:3629`) returns `'void *'` ON PURPOSE, with the measurement in its own comment: typing it `MojoList *` broke `funcs_shared.py`'s nested-tuple comprehension target over `zip` and took the whole self-host compile down. | INTENDED. `types.py:321`'s `'zip': 'MojoList *'` is the STALE half of that pair and disagrees with it — a real (small) inconsistency, recorded, not fixed here |
| `Span *` | `iter(x)` in value position is a bare identity: `emit_calls.py:1914-1915` returns `gen.lower_expr(node.args[0])`. And `emit_stmts._try_bind_list_iter` declines to bind a cursor unless the argument lowers to `MojoList *` (or an int), so `Span *` gets none. | A real gap, but in the CURSOR mechanism, not in "the erasure" |

So the defect underneath shape 2 is one sentence: **these value forms produce
materialized SEQUENCES, and a caller that stores one in a variable and calls
`next()` on the variable is correct Mojo with no lowering.** That is fixable,
and is (b).

#### (b) The fix, measured, and PARKED because 2 of the 3 files cannot link

`it = enumerate(x)` now binds the same resumable cursor `it = iter(<list>)`
already binds (`emit_stmts._try_bind_list_iter`), so `next(it)` advances a real
position and `for v in it:` resumes. Measured:

    compile_stdlib.py   591 / 19 / 0  ->  594 / 16 / 0, 0 unexpected, exit 0
    test/iter/test_enumerate.mojo          COMPILED   (was: refused, `MojoList *`)
    test/collections/test_set.mojo         COMPILED   (was: refused, `MojoList *`)
    test/python/test_python_object.mojo     COMPILED   (was: refused, `MojoList *`)
    test/iter/test_zip.mojo                still refused (`void *`, by design)
    undef_import_census  96 / 51 / 60 unchanged

Generated C for the minimal case (`var it = enumerate(s); var elem = next(it)`)
is a pair-materialising loop exactly as before, plus `cur = 0;` and a cursor
read — the list, its element kind and its per-slot kinds are untouched, so
`len(it)` and `it[i]` behave identically. The whole 7-site blast radius of
`= enumerate(` in the stdlib is inside the three files above (measured by
grep), so no currently-compiling file changes.

**Parked, in `git stash@{0}`, and the reason is the acceptance bar, not
doubt.** `tools/linkcheck.py`, which subtracts libc:

| file | undefined after runtime + dylib | verdict |
|---|---|---|
| `test/iter/test_empty.mojo` (already green since round 2) | 11 — the libc + `std.testing`-stub baseline | the bar, as it is actually applied |
| `test/iter/test_enumerate.mojo` | **8 — exactly that baseline** | would pass |
| `test/collections/test_set.mojo` | 16, incl. `_Set` | would not |
| `test/python/test_python_object.mojo` | 18, incl. `_Python`, `_PythonObject`, `_int64_t_as_unsafe_any_origin` | would not |

The two that would not pass fail for reasons that have nothing to do with this
change and pre-date it: `_Set` is the census's own generic-struct family (1 of
its 51 names), `_Python`/`_PythonObject` are imported STRUCT TYPES called as
functions, and `_int64_t_as_unsafe_any_origin` / `conforms_to` are names this
codegen synthesises that exist nowhere in the stdlib or the runtime. Those
files are in `EXPECTED_FAILURES` and must STAY there — and because they now
PASS `gcc -fsyntax-only`, `compile_stdlib.py`'s stale-marker rule
(`sys.exit(1)` on any entry whose file passes, `compile_stdlib.py:641`) fires
and the sweep cannot be 0-unexpected. So the change is correct, is worth
3 files, and cannot be landed until those symbols are closed. It is in the
stash with that reasoning as its message; `git stash pop` restores it.

#### (c) The acceptance bar — "LINKS with no undefined symbols" — is met by
**ZERO** of the 594 currently-green files. This is why (b) is parked and not
nudged through.

Measured with `tools/linkcheck.py`, same flags, same dylib:

    test/iter/test_empty.mojo          11 undefined   (green since round 2)
    test/memory/test_maybe_uninit.mojo  13 undefined   (green)
    test/collections/test_list.mojo     22 undefined   (green)

and `test_maybe_uninit` / `test_list` carry `_conforms_to`, `_type_of`,
`_PropTest`, `_int64_t_as_imm`, `_size_of_6_target_…_Int` — the same declared-
stub-called-but-never-defined family the three files above would carry. So the
bar as written in the plan, applied literally, would return all 594 green
files to `EXPECTED_FAILURES`. The criterion that IS satisfiable, and the one
used above, is: *the file's undefined set must not exceed the classes an
accepted-green file already carries* — libc, the `std.testing`/`test_utils`
helper stubs `linkcheck.py` documents, and the elaborated-into-a-mangled-symbol
family. On that criterion `test_enumerate` passes and the other two do not,
which is exactly the split in (b). Stated as UNVERIFIED: whether the other two
files' residues would be acceptable is a judgement about the standard, and
`test_enumerate`'s own `assert_equal`s are STUBBED in that link, so this link
observes that it links, not that its assertions pass.

#### (d) Shape 3 does not reach either of its two files, and the reason is
not `Self.` handling

The plan's shape 3 is "`Self.<comptime member>` read from the struct's own
declaration, and accept an `Origin[...]` type argument as concrete". Measured:

1. **`Self.<param>` substitution already works and is not the blocker.**
   `monomorphize.monomorphize_source` for `BytesIter` with `{origin: String}`
   yields `var _iter: _SpanIter[Byte, String]` (verified). ae8f0493's scoping
   was right.
2. **The two modules compile their OWN template, un-monomorphized.** Measured
   in `iterators.mojo`: `gen.struct_field_types['BytesIter'] ==
   {'origin': 'int64_t', '_iter': 'int64_t'}`. `itertools.mojo` is the same
   shape with a bare type parameter (`_Product2`'s `var _inner_a:
   Self.IteratorTypeA`, and nine `next(self._…)` sites over fields typed that
   way). **Neither module constructs its own generic struct at a concrete type
   argument anywhere**, so there is no in-TU instantiation for a substitution
   to feed, and no amount of `Self.` reading or origin awareness gives the
   template body a receiver type. Reading `Self.<comptime member>` cannot fix a
   template whose member is unbound.
3. **The INSTANTIATION half is blocked by two other things, in order.**
   (a) `monomorphize.instantiate` builds its TU from the EXTRACTED TEMPLATE
   TEXT ONLY (`monomorphize.py:396-425`), so the fragment carries none of its
   module's `from … import` lines and cannot see `_SpanIter` at all. Verified
   by prepending the one needed import by hand: `_SpanIter` then registers in
   `gen._imported_generic_structs`. (b) even registered, the field stays
   `int64_t`, because `_materialize_generic_struct_mentions` is never applied
   to a LOCAL struct's field annotation (only to generic RETURN annotations,
   via `_refine_generic_return_type`'s hook, and to `_generic_struct_field_types`
   on the caller side) — and because the elaboration declines regardless:
   `_SpanIter[Byte, String]` binds `mut = Byte` and leaves `T`, `origin` and
   `forward` unbound, so `elaborate_generic_struct` returns `None`.

   **The third sub-problem, which the plan does not name: the stdlib spells
   `_SpanIter` with TWO positional arguments and `_SpanIter`'s own head is
   `[mut: Bool, //, T: Copyable, origin: Origin[mut=mut], forward: Bool = True]`
   (`span.mojo:84-90`).** `span.mojo:207` and `:214`, `reversed.mojo:232` and
   `iterators.mojo:908` all pass `[<element type>, <origin>]`. So `mut` — which
   `origin`'s own annotation depends on (`Origin[mut=mut]`) — is unbindable
   from the stdlib's own spelling. That is a stdlib/elaborator interface
   question and it is upstream of anything in this doc.

#### The next step, stated as one thing

`enumerate(x)`'s cursor binding (b) is finished and correct; it needs `_Set`,
`_Python`, `_PythonObject` and `int64_t_as_unsafe_any_origin` to exist before it
can be landed, and those are ordinary census/section-2 items. After it,
shape 2 is closed and `test/iter/test_zip.mojo` needs a decision about
`_lower_builtin_zip_n`'s deliberate `void *` (its own comment names the
self-host shape that forced it). Shapes 1 and 3 are untouched by (b) and still
need dependent return types plus overload selection — and shape 3 additionally
needs the `_SpanIter` head question above answered.

### MEASURED 2026-10-03 (merged tree): the `Span *` receiver is GONE, and the
### in-TU pass's wall is `_concrete_args`, NOT `_protocol_only_overloads`

Re-measured after the 2026-10-03 merge of the parallel tree. Two results, one
of which corrects where this doc's own "what is still open" table points the
next session.

**1. One file out of the family, and it needed no inference at all.** 19 → 18.
`test/collections/test_span.mojo` was the only member whose receiver was a REAL
pointer rather than a boxed integer (`Span *`, per the table below), so nothing
about the callee's type had to be inferred. Three defects stood between the
iterator cursor and that receiver, all now fixed and none of them about type
inference:

* `_try_bind_list_iter` (now `_try_bind_iter_cursor`) gated the cursor on
  `MojoList *`, so a `Span *` got no cursor at all and `next(it)` had no
  receiver to dispatch on. The gate is now `emit_calls._struct_data_field` +
  a `_len` field — the same predicate `_lower_subscript` uses to read `span[i]`
  — so the two agree by construction. All six cursor readers now go through
  `mojo/middle/itcursor.py`; before that they were four half-implementations
  across three back-end files.
* `len(<cursor>)` answered the CONTAINER's total length, unchanged by every
  `next()` that had already run. Wrong on the list cursor too — this was not a
  Span-only defect.
* `Span(<list>)` stored the list POINTER in `_data` and left `_len` unset, and
  `span[i]`'s tracked-element branch required a known STRUCT element, so every
  numeric span read one byte where the element is eight.

Artifact evidence, because `compile_stdlib.py` is `gcc -fsyntax-only` and
cannot see any of this: the module's own object defines `_mojo_at_int64_t` and
uses it for every cursor read, and `tools/linkcheck.py
test/collections/test_span.mojo` leaves 17 undefined symbols against
runtime + the dylib, of which 8 are libc and 3 are `std.testing`'s
`assert_equal`/`assert_raises`/`assert_true` — the same baseline as
`test/iter/test_empty.mojo`, which was accepted green in the round above (11).
The remaining 6 are `_Span_apply`, `_Span_binary_search_by`, `_std_math_
___init___iota`, `_std_memory___init___forget_deinit_9f63a2` and
`_check_write_to`: methods and functions this file CALLS and that live in
other stdlib modules the single-module link does not build. **No cursor, `next`
or iterator symbol is undefined** — which is the thing `linkcheck.py`'s own
docstring says the instrument exists to catch.

**2. The in-TU pass's wall is `_concrete_args`, not `_protocol_only_overloads`,
and widening the latter changes nothing.** The table below, and the "honest
boundary" section under "Landed 2026-10-03", both leave the impression that a
struct whose duplicated method names reach outside the iteration protocol is
what stops the `std/itertools` family (`_TakeIterator` duplicates `__init__`).
Measured: adding `'__init__'` to `elab_intu._ITERATION_PROTOCOL` and
recompiling `test/itertools/test_take.mojo` produces **zero** in-TU
instantiations and the identical `next(...)` refusal on the identical receiver
type. The refusal happens EARLIER, in `_concrete_args`, which accepts only two
readable sources of a type argument — explicit bracket arguments, or an argument
list that is ALL literals — and `take(nums, 3)` is neither (`nums` is a local,
so nothing has a type yet: the pass runs before any lowering). So the order is:

1. `_concrete_args` needs the callee's bracket arguments, which needs argument
   TYPES, which needs a static pass over the module's own statements — nothing
   has a C type at this point in `gen_module`.
2. Only then does `_protocol_only_overloads` matter, and only because
   `_TakeIterator` duplicates `__init__`.

**And step 1 alone would not be enough.** `take`'s return annotation is
`_TakeIterator[IterableType.IteratorType[origin]]`, so binding `IterableType`
from the argument still leaves a return type that is not a CONCRETE struct name:
`IterableType.IteratorType[origin]` is an ASSOCIATED TYPE of the argument's
type, read from `comptime IteratorType[...] : Iterator = <expr>` in the
struct's own declaration and substituted over its type parameters. Both halves
are needed, in that order, and both are shared infrastructure the `formal`
target-query inference wants too — which is why this doc has said for several
rounds that the associated-type resolution is the part worth building once.

**3. Receiver types, re-measured on the merged tree** (the "refusal SITE"
table further down is unchanged in substance; this is the count after the Span
removal): `int64_t` 13, `MojoList *` 3 (`test_set`, `test_enumerate`,
`test_python_object` — all `enumerate(x)` in value position), `void *` 1
(`test_zip`, `_lower_builtin_zip_n`'s deliberate choice), and one file that is
not this bug at all (`test/os/path/test_getsize.mojo`, the `stat` out-param).

### MEASURED 2026-10-03: where each of the remaining 17 actually refuses

The table above names the GENERIC each file needs. This one names the exact
refusal SITE — file, line, the receiver's C type as codegen computed it, and
the source line — by instrumenting `emit_calls._lower_call` and re-raising, so
every row is an observation rather than an inference. Re-measurable with the
snippet in this section's last paragraph.

| file | line | receiver C type | the source line that refuses |
|---|---|---|---|
| `std/collections/string/iterators.mojo` | 938 | `int64_t` | `return next(self._iter)` |
| `std/itertools/itertools.mojo` | 140 | `int64_t` | `self._inner_a_elem = next(self._inner_a)` |
| `test/collections/string/test_iterators.mojo` | 165 | `int64_t` | `_ = next(bytes)` |
| `test/collections/test_set.mojo` | 231 | `MojoList *` | `var elem = next(it)` |
| `test/collections/test_span.mojo` | 544 | `Span *` | `assert_equal(next(it), 1)` |
| `test/iter/test_chain.mojo` | 24 | `int64_t` | `assert_equal(next(it), 1)` |
| `test/iter/test_enumerate.mojo` | 20 | `MojoList *` | `var elem = next(it)` |
| `test/iter/test_map.mojo` | 25 | `int64_t` | `assert_equal(next(m), 2)` |
| `test/iter/test_peek.mojo` | 22 | `int64_t` | `_ = next(iter)` |
| `test/iter/test_zip.mojo` | 27 | `void *` | `var elem = next(it)` |
| `test/itertools/test_cycle.mojo` | 30 | `int64_t` | `assert_equal(next(it), 1)` |
| `test/itertools/test_drop.mojo` | 27 | `int64_t` | `assert_equal(next(it), 3)` |
| `test/itertools/test_drop_while.mojo` | 48 | `int64_t` | `assert_equal(next(it), 5)` |
| `test/itertools/test_product.mojo` | 32 | `int64_t` | `var elem = next(it)` |
| `test/itertools/test_take.mojo` | 27 | `int64_t` | `assert_equal(next(it), 1)` |
| `test/itertools/test_take_while.mojo` | 47 | `int64_t` | `assert_equal(next(it), 1)` |
| `test/python/test_python_object.mojo` | 296 | `MojoList *` | `var val = next(it)` |

(`test/os/path/test_getsize.mojo` is the separate `stat` defect and
`test/itertools/test_count.mojo` is item 1; neither appears here.)

**Three shapes, not one, and only the first is the common case.**

> **Shapes 2 and 3 below are MIS-DIAGNOSED; read the ROUND 4 section above
> before acting on either.** Shape 2's three C types are all deliberate builtin
> lowerings (not "the erasure picking a container"), and its fix is BUILT and
> PARKED. Shape 3's two sub-problems do not include the one this section names:
> `Self.<param>` substitution already works, the two modules compile their own
> un-monomorphized template, and the instantiation half is blocked first by the
> fragment carrying no imports and then by the stdlib's two-positional-argument
> spelling of `_SpanIter`'s five-parameter head. Round 4 (a)–(d) has the
> measurements. Shape 1 below is unaffected and still correct.

1. **`int64_t` (11 files) — the receiver is BOXED.** The local was bound from
   a call that returned an un-elaborated generic, so codegen never learned a
   struct type for it. This is items 2 and 3.
2. **`MojoList *` / `Span *` / `void *` (6 files) — the receiver is a real
   POINTER, to the wrong thing.** `var it = enumerate(list_obj.__iter__())`
   types `it` as `MojoList *`: the erasure picked a container for an argument
   it could not resolve, rather than the scalar `int64_t` of case 1. The
   refusal is consequently a DIFFERENT one — `_lower_call`'s struct branch
   computes `_struct_ptr_name(gen, 'MojoList *')`, finds no `MojoList___next__`
   in `func_return_types`, and refuses — and it will NOT be fixed by whatever
   fixes case 1. Worth separating before starting, because a fix aimed at case 1
   that measures only "did the refusal count go down" will look like progress
   here while changing nothing. `test_zip`'s `void *` is a third variant again:
   `zip(l, l2)` erased to an untyped pointer rather than to any named struct.
3. **`self._iter` (2 files) — the receiver is a FIELD of a struct in the same
   module, typed by an IMPORTED GENERIC'S INSTANTIATION.** `iterators.mojo`'s
   `BytesIter[origin: ImmOrigin]` declares
   `var _iter: _SpanIter[Byte, Self.origin]` and its `__next__` does
   `next(self._iter)`. Two distinct sub-problems, and this is the one item 3
   is actually about: (a) `Self.origin` appears as a type ARGUMENT inside a
   nested instantiation, not as a bare `Self.<TYPE PARAM>`, so commit
   ae8f0493's substitution does not reach it; (b) even substituted, the result
   `_SpanIter[Byte, <origin>]` is not a CONCRETE type name, so
   `_materialize_generic_struct_mentions`' `_is_concrete_type_arg` check
   declines it — an `Origin[...]` argument needs origin-aware elaboration, not
   a name. `test_iterators.mojo`'s `_ = next(bytes)` is the same shape reached
   through a method (`StringSlice.bytes()` returns `BytesIter[origin]`).

   **This is the concrete next step, and it is narrower than items 2/3**: it
   is two files, it is one field shape, and it does not need overload selection
   at all. It needs (a) `Self.<comptime member>` read from the struct's own
   `comptime`/`[...]` declaration in its DEFINING module and substituted
   (explicitly NOT textual `Self.` stripping — see ae8f0493), and (b) an
   origin-typed type argument accepted as concrete by the materializer.

To reproduce the table, wrap `mojo/backend_gimple/emit_calls._lower_call`, log
`getattr(node, 'line', 0)` and the receiver C type parsed out of the
`receiver typed \`…\`` clause of the RuntimeError, re-raise, and call
`build_stdlib_dylib.compile_module_to_c` once per file.

### Landed 2026-10-03: in-TU instantiation, and 3 of the 22 with it

`mojo/backend_gimple/elab_intu.py` (new) + one call site in
`mojo/backend_gimple/module_gen.py` + two suppression hooks in
`emit_resolve.py` + one registry in `gimple_codegen.py` consumed by
`emit_loops.py` and `emit_calls.py`.

**What it is.** Before any function body is lowered, the pass finds the
generic call sites in the module's OWN parsed statements, monomorphizes each
to SOURCE, PARSES it, and appends the result to `gen_module`'s `stmts`. Every
downstream pass is unchanged: struct registration, `func_return_types`, the
struct-typedef emission and `_local_top_level_func_names` all read `stmts`
once and now see the instantiation. The two consumers this exists for —
`emit_calls._lower_call`'s `next(<struct>)` and `emit_loops._gen_for_struct_iter`'s
`for x in <struct>` — then dispatch with real, host-inferred method names.

The call site must stay **after** `_local_struct_names` (so the materialized
struct is not claimed as this module's own, and its method symbols stay BARE,
matching both `_struct_method_csym(name, m, '')` at every call site and the
elaboration TU's own `module_name=''` build) and **before** `all_struct_defs`
(so the struct gets a layout, not just a name). Both directions are load-bearing
and both are stated at the call site.

**The previous session's `conflicting types` was NOT the cause, and that is
measured, not assumed.** That failure is a definition with real parameter types
sitting beside a declaration with the elaborator's erased ones, and it comes
from the two routes BOTH claiming one instantiation. This pass removes the
second claim outright: `_ensure_generic_struct` and `_elaborate_generic_call`
return early for anything `gen._intu_*_args` already holds, so no `extern` and
no CAS object is emitted beside an in-TU definition. **Zero `conflicting types`
in the 591-file sweep.** What the sweep DID show is a different and previously
unmeasured blocker, below.

**The real remaining blocker is that in-TU changes a struct from erased to
REAL, and this codegen's real-struct machinery is incomplete.** Measured, all
from widening the pass to every generic struct with a duplicated method name:

| what in-TU exposed | files | the gap |
|---|---|---|
| `[i] = v` on a now-real container struct | 4 (`std/os/process.mojo`, `std/python/_cpython.mojo`, `test/collections/test_conditional.mojo`, `test/memory/test_arc.mojo`) | `error: ... subscript store on user-defined struct 'List_1_T_...' (no __setitem__ method and no backing container field)` |
| an overloaded NON-protocol method's call site still holds the erased view | 7 (`test/collections/test_{list,deque,interval,linked_list,optional}.mojo`, `test/builtin/test_device_passable.mojo`, `test/format/compile_fail/test_writable_error.mojo`) | `error: passing argument 2 of 'MoveCounter_...___init___fa7888' makes integer from pointer without a cast` |
| one instantiation, two spellings | `test/utils/test_coord.mojo`, `test/ffi/test_unsafe_union.mojo` | `error: redefinition of 'Coord_...___init___0120be'` — two StructDefs with the same name, because `Coord[ComptimeInt[5], Coord[Int32, ComptimeInt[3]], Int64]` and `Coord[ComptimeInt[5], Int32, ComptimeInt[3], Int64]` bind the same values and mangle identically. **Fixed** by keying the worklist on the MANGLED NAME, which is the whole reason it is injective |

So the honest boundary of the feature, and it is measured rather than a
convenience: **in-TU carries a struct whose only duplicated method names are
iteration-protocol ones.** The justification is structural — the two consumers
resolve `__iter__` by the bare name and correctly fall back to "keep the
receiver's own type" when it is absent, so an overloaded `__iter__` costs them
nothing — while every OTHER overloaded method is dispatched through its
signature hash, and this codegen cannot yet pick an overload at a call site
from real C parameter types.

| duplicated method names | verdict | measured examples |
|---|---|---|
| `['__iter__']` | in-TU | `_Empty`, `_Once`, `_PeekableIterator`, `_MapIterator`, `_ZipIterator`, `_ChainedIterator`, `_Enumerate`, `_RepeatIterator` |
| `['__init__']` | refused | `MoveCounter`, `ArcPointer`, `BitSet`, `StaticTuple` |
| `['__eq__', '__init__', '__iter__']` | refused | `Optional` |
| `['__getitem__', '__init__', '__iter__', 'extend', 'pop', 'resize']` | refused | `List` |
| `['__init__', '__len__', 'product']` | refused | `Coord` |

A refused case is REFUSED — the `.o` route runs for it exactly as before — not
narrowed into a second definition.

**Two real defects this uncovered, both landed.**

1. **`func_return_types` claimed a symbol nothing defines.** Every method of a
   struct got a bare `{Struct}_{method}` entry, including an OVERLOADED one,
   whose real symbols are `__iter___0120be` / `_0120be_2`. Both protocol
   consumers read that entry as "callable under that name", and
   `test/itertools/test_repeat.mojo` linked with `Undefined symbols:
   __RepeatIterator_11_ElementType_5_Int64___iter__`, called from BOTH of its
   `for` loops. `gen._ambiguous_struct_methods` now publishes the ambiguity
   and both consumers consult it.
   *Attempted and measured wrong:* deleting the bare `func_return_types` entry
   instead. The forward-declaration emitter falls back to its variadic-sentinel
   parameter list for the suffixed names, and the declaration and the definition
   then disagree — `error: conflicting types for
   'std_collections_set_Set___iter___0120be'; have 'int64_t(Set *)' ...
   previous definition ... with type 'int64_t(Set *, ...)'` on
   `std/collections/set.mojo`, plus `std/ffi/__init__.mojo`,
   `std/python/_cpython.mojo`, `test/sys/test_dlhandle.mojo`. Four red files.
   The bare entry has to STAY; that is why this is a separate registry.

2. **`_elaborate_generic_call` must decline BEFORE it lowers an argument.**
   Suppressing it after `arg_pairs = [gen.lower_expr(a) for a in node.args]`
   would emit every argument's statements and then fall through to lower them
   all again.

**Per-file evidence for the three removals** (`nm -g` after a real `gcc -c`):

    test_empty   T _empty_1_T_3_Int
                 T __Empty_1_T_3_Int___iter___0120be / _0120be_2
                 T __Empty_1_T_3_Int___next__
                 T __Empty_1_T_3_Int_bounds
    test_once    T _once_1_T_5_Int64
                 T __Once_1_T_5_Int64___next__ / T __Once_1_T_5_Int64_bounds
    test_repeat  T _repeat_11_ElementType_5_Int64 and _repeat_11_ElementType_6_String
                 T __RepeatIterator_11_ElementType_5_Int64___next__

and a real `ld` of each module's C against `runtime/fire_runtime.c` leaves no
undefined iterator symbol and the binary exits 0. **Stated precisely because
it is weaker than a passing test suite:** the `std.testing` `assert_equal` /
`assert_raises` helpers are STUBBED in that link (this driver compiles one
module, not `std.testing`), so the assertions inside these three files were
not themselves observed to pass. What is verified is that the module's own
object defines the instantiation and its `__next__`, that nothing is left
undefined, and that the program runs to completion.

**`once(10)` / `repeat(42, times=3)` needed no inference at all**, which is
what the previous session predicted: the type argument is the LITERAL's own
exact Mojo type, read through the elaborator's own unifier
(`elaborate.infer_type_args` / `infer_struct_type_args`) so this pass and the
`.o` route cannot disagree about what those arguments mean.

| | before | after |
|---|---|---|
| `compile_stdlib.py` | 588 / 22 / 0 | **591 / 19 / 0** |
| `undef_import_census.py` | 96 / 51 / 60 | 96 / 51 / 60 (unchanged — the three were never in it; see above) |
| `test_module_cache.py` | 131 / 0 | **142 / 0** (`test_in_tu_instantiation`: the boundary predicate on the real stdlib templates, and the three modules' own C defining their instantiation with no `extern` and no bare `__iter__` call) |
| `test_gimple.py` | 354 / 0 | 354 / 0 |
| `test_link_mode.py` | 11 / 0 | 11 / 0 |

**What is still open, in the order the next session should take it.** Measured
per file: 18 of the 19 remaining failures are the SAME `next(...)` refusal on
a boxed receiver, and the generics they call are listed here so the next step
is not a guess.

| file | the generic(s) it needs |
|---|---|
| `test/iter/test_peek.mojo` | `peekable` |
| `test/iter/test_chain.mojo` | `chain` |
| `test/iter/test_map.mojo`, `test/itertools/test_drop_while.mojo`, `test/itertools/test_take_while.mojo` | `map`, `drop_while`, `take_while` (all via `map`-shaped closures) |
| `test/iter/test_zip.mojo` | `zip` |
| `test/iter/test_enumerate.mojo`, `test/collections/test_set.mojo`, `test/collections/string/test_iterators.mojo`, `test/python/test_python_object.mojo` | `enumerate` |
| `test/itertools/test_take.mojo`, `test/itertools/test_drop.mojo` | `take`, `drop` |
| `test/itertools/test_cycle.mojo` | `cycle` |
| `test/itertools/test_product.mojo` | `product` (three arities) |
| `std/itertools/itertools.mojo`, `std/collections/string/iterators.mojo` | the whole family, module-wide |
| `test/collections/test_span.mojo` | `enumerate`, `iter` |
| **`test/itertools/test_count.mojo`** | **neither — but see item 1 below: it is DOWNSTREAM of `std/itertools/itertools.mojo` compiling, not independent of it** |
| `test/os/path/test_getsize.mojo` | neither — the unrelated `getsize` `gcc -c` failure already documented |

1. **A concrete imported function whose return annotation names a struct in its
   own module.** `test_count.mojo` is the whole of this and it is NOT a generic
   problem at all: `def count(start: Int = 0, step: Int = 1) -> _CountIterator`
   is an ordinary function, `_CountIterator` is an ordinary struct, and the
   importer writes `from std.itertools import count` — so neither is ever
   registered. Measured on that file: `_imported_symbols` is empty, `count` is
   in neither `_imported_generics` nor `imported_symbols`,
   `struct_field_types` has no `_CountIterator`, and the call's result types as
   the boxed `int64_t` that `next(it)` then refuses. The honest unblock is to
   register the struct a concrete imported function returns, which is
   struct-inlining for a struct with no template — and that carries the SAME
   real-struct risk the in-TU widening measured above, so it wants the
   `test/itertools/test_count.mojo` artifact as its acceptance bar (its object
   must define `_CountIterator___next__`), not a green syntax check.

   ### Item 1 is BUILT and measured, and it is BLOCKED AT THE LINK — reverted, not landed

   2026-10-03. The three-part change is written, it compiles all 592 files
   with **0 unexpected**, it makes `test/itertools/test_count.mojo` pass
   `gcc -fgimple -fsyntax-only` for the first time, and it was **reverted**
   because the acceptance bar this very section sets is not met. Reverted with
   `git stash push` (recoverable; nothing was discarded) rather than landed,
   because landing it would have removed `test_count.mojo` from
   `EXPECTED_FAILURES` on the strength of a green SYNTAX check whose artifact
   links to nothing — the exact trade this project rejects.

   **What it is, and each half is a real defect rather than a guess.**

   - **`_imported_func_return_struct` asked two questions in the wrong order,
      and with the wrong test.** It looked for `def count` in the module the
      import STATEMENT names, and then gated the result on
      `_rbase[0].isupper()`. Both are wrong for every stdlib package. (a)
      `from std.itertools import count` names `std/itertools/__init__.mojo`,
      which is a docstring plus a `from .itertools import (count, cycle, …)`
      re-export list and defines no function at all, so the lookup found
      nothing. It now resolves the DEFINING module first
      (`_find_symbol_home_module(..., want_abs=True)` → `std.itertools.itertools`;
      `want_abs` because the answer is used to open a file and the default
      spelling is the bare relative ref `.itertools`, which no resolver
      accepts standalone — measured). (b) `isupper()` is a naming convention
      the stdlib's own iterator structs break: the return struct is
      `_CountIterator`, so `count` was declined while a public non-underscore
      twin was accepted. Replaced with `_find_imported_struct`, i.e. the real
      parse tree — strictly stronger than capitalization, and the same
      predicate `_materialize_imported_struct` applies next.
   - **The struct a function RETURNS was never materialized, because the
     registration loop only fires when the imported NAME is itself a struct.**
     `_locally_constructed[_ret_struct]` was dead: nothing looked up that key,
     because it is not an imported name. New block consumes it, scoped to
     "the call's result is ASSIGNED to a name" (a bare in-place use is
     excluded on purpose — see the UTF8Chunks measurement at
     `_locally_constructed`'s own definition).
   - **The recorded return type was the text scan's erasure, and that is a
     WRONG SIGNATURE, not a missed optimization.** `module_loader` scans text
     and erases every struct to `int64_t`, so `count` arrives as
     `c_return_type: 'int64_t'` while the defining module emits
     `_CountIterator *`. Both declaration sites (`_emit_stdlib_import_externs`
     and `_register_sym`) now correct it from the defining module's parse,
     gated on `struct_field_types` already holding the struct — i.e. only when
     some earlier pass in THIS compile resolved its real field layout.

   **Measured result.** `test_count.mojo` goes from a compile-time refusal to
   `gcc rc=0`, `it` typed `_CountIterator *`, the call reading
   `_t1 = std_itertools___init___count_2dbb98 (_t2, _t3); _t4 =
   std_itertools_itertools__CountIterator___next__ (it);`.

   **The symbol agreement it bought is real and was checked from both sides**
   (`tools/linkcheck.py`, new, and `tools/dumpc.py`, new):

       caller  : extern int64_t std_itertools_itertools__CountIterator___next__ (_CountIterator *);
       definer : nm -g -> T _std_itertools_itertools__CountIterator___next__      AGREE
       caller  : extern _CountIterator * std_itertools___init___count_2dbb98 (int64_t, int64_t);
       definer : nm -g -> T _std_itertools_itertools_count_2dbb98                DISAGREE

   **Why it is reverted — two blockers, both outside `test_count.mojo`, both
   pre-existing, and the second one decisive.**

   1. `count`'s own symbol qualifier names the RE-EXPORTING package, not the
      defining module: the caller composes `std_itertools___init___count_…`
      from `std/itertools/__init__.mojo`, the definer emits
      `std_itertools_itertools_count_…`. Measured as pre-existing (the
      unmodified tree emits the same `std_itertools___init___count_2dbb98`),
      and it is filed separately as
      `bugs/CODEGEN_reexported_function_import_qualifier_names_the_wrong_module.md`
      (`bugs/hard/README.md`). Not fixed here: `_func_qualifier`'s tier-2
      `_own_imported_func_home` is load-bearing for two documented miscompiles,
      and re-deriving it reaches every `from <pkg> import f` across the 51
      stdlib packages — not landable without the gate.
   2. **`std/itertools/itertools.mojo` does not compile at all**, so `count`
      and `_CountIterator.__next__` exist in NO object.
      `nm -gU build/libmojostdlib.arm64.dylib | grep itertools` returns exactly
      two symbols (`__std_itertools___init___toplevel`,
      `_std_itertools___init___init`) — the module was never built. Its own
      failure is `next(self._inner_a)` at line 140, inside `_Product2.__next__`
      — a MemberExpr whose receiver is the generic struct FIELD
      `_inner_a: IteratorTypeA`, i.e. a TYPE PARAMETER, which is item 2/3
      below. So `test_count.mojo` is DOWNSTREAM of the whole remaining family,
      not independent of it. This is what round 2's itemisation did not
      measure.

   **Consequence for the next session, stated as the precise next step.** Item
   1 is four edits in four files and is not the bottleneck; it is blocked
   BEHIND items 2 and 3. Do items 2/3 first. When `std/itertools/itertools.mojo`
   compiles, item 1 applies and `test_count.mojo` should then be checked with
   `tools/linkcheck.py test/itertools/test_count.mojo`, whose remaining
   undefined symbol must be `count`'s qualifier alone — at which point that is
   the re-export bug, not this one.

   **Also measured while building it, and reusable.** Correcting a recorded
   return type to a real struct pointer collides with the `extern` block that
   is flushed BEFORE the struct typedefs (`_link_import_decl_list` at
   `gen_module_impl`, ahead of the `struct_field_types` typedef loop), and the
   collision has two distinct shapes that need two different fixes:
   `error: unknown type name '_CountIterator'` (the type is not yet complete)
   and `error: conflicting types for
   'std_python_bindings_lookup_py_type_object'; have 'PythonObject *(void)'`
   (two same-named externs of different types). The second is the subtle one:
   the predicate that decides "does this declaration name a struct" must be
   evaluated at the FLUSH, keyed on the symbol's CURRENTLY RECORDED type and
   matched through the tree's one `_func_csym` composer — not at queue time and
   not against the declaration's own text. Evaluated at queue time it sees a
   `struct_field_types` that is not yet complete, because
   `_register_imported_structs` runs early and the `_register_sym`
   FromImportStmt walk runs much later; the two sites then disagree. Building
   the set at the flush also has to snapshot `func_return_types` first
   (`list(...)`): `_func_csym` can register into it, and iterating directly
   raises `dictionary changed size during iteration` on `std/pwd/pwd.mojo`.
2. **Overload selection on a trait bound**, which is the dominant blocker in the
   table: `peekable`'s `Some[Iterable]` vs `Some[IterableOwned]`, `map`'s and
   `take_while`'s thin-vs-owned pairs, `product`'s three arities, `zip`'s pair.
   `Elaborator.elaborate_overload_call` matches on `c_to_mojo`'s scalar reverse
   table, which cannot answer a conformance question; `check_conformance` and
   `Some[...]` already exist and the table is what has to learn to ask them.

   ### MEASURED 2026-10-03: the elaborator does NOT first-pick here, and the
   ### silent first-pick was in the INTERPRETER — fixed; the elaborator's real
   ### limitation is stated precisely below.

   The previous plan said `elaborate_overload_call` "matches on a scalar
   reverse table, which cannot answer a conformance question", and implied that
   it then picked something. Checked rather than assumed, and the two halves
   come apart:

   - **It matches on the RAW annotation, not the erased one, so it cannot tie.**
     `elaborate_overload_call` compares `ptypes == arg_mojo` where `ptypes` is
     each overload's declared annotation VERBATIM (`extract_overloads` reads
     them off the parse tree) and `arg_mojo` is `c_to_mojo(arg_ctypes[i])`,
     whose every value is a scalar name (`Int64`, `Int`, `String`, `Float64`,
     …). So a match requires the annotation to literally BE one of those names;
     `Some[Iterable]` never equals `Int`. Measured over every non-generic
     overload group in the stdlib (98 of them; `extract_overloads`' pattern
     requires `(` right after the name, so bracketed templates are excluded and
     must not be counted here): **14 groups have at least one matchable
     overload, and 0 have a DUPLICATED matchable annotation.** There is no tie
     to refuse, because the matcher is comparing two different kinds of thing
     and the answer is reliably "no".

   - **So `peekable` is declined, not mis-picked — and the decline
     MISDESCRIBES ITSELF.** Both candidates are visible and distinguishable
     (`('Some[Iterable]',)` vs `('Some[IterableOwned]',)`), yet the decline
     reads as "no overload matches these argument types", which is false. The
     real reason is that the resolver holds a scalar C type where answering
     needs the argument's Mojo type.

   - **Mojo's real rule, and whether it is derivable from the stdlib source:
     NO, and it is worth stating why rather than leaving it open.** The
     discriminator between `std/iter/__init__.mojo`'s two `peekable` overloads
     is the argument's *parameter convention* (`ref iterable: Some[Iterable]`
     vs `var iterable: Some[IterableOwned]`) plus conformance of the argument's
     type to `Iterable` vs `IterableOwned`. Both facts live in the ARGUMENT, and
     the argument reaches this code as an erased C type: `c_to_mojo` is a scalar
     reverse table, so `MojoList *` and a `String *` and an `int64_t` all arrive
     as scalars and an owned `MojoList` satisfies BOTH traits — a real tie that
     no amount of reading the trait declarations resolves. Recovering it needs
     the argument's Mojo type at the call site, which is item 3's machinery
     (`_refine_generic_return_type` does not receive argument types either).
     **So: do not guess these, and do not build a conformance checker against
     an erased type — it would be answering a question it cannot see.**

   - **The actual "silently picks the first" antipattern was
     `myinterpreter.MojoOverloadSet`, and it is FIXED (landed 2026-10-03).**
     `__call__` returned the first candidate `_matches` accepted, and
     `_matches` looks only at argument count and keyword names — so the
     stdlib's own `peekable` pair (same arity, no keywords, differing only in a
     trait bound and a convention) dispatched to whichever the file declared
     first. Its class docstring claimed "no match is a hard error rather than a
     silent first-pick", which was true of the no-match branch and **false of
     the ambiguous one**. It now collects all matching candidates, raises
     `_NoOverloadMatch` naming the tie when more than one survives, and still
     dispatches when exactly one does. Pinned by
     `test_module_cache.py::test_ambiguous_overload_is_refused_not_first_picked`
     (4 checks: the tie raises, the message names the candidates, a RANKABLE
     set still dispatches so the refusal cannot over-reach, and the pre-existing
     no-match error is unchanged). Measured blast radius: none —
     `test_runtime_diff.py` 42/0, `test_interp_oracle.py` 6/0,
     `test_generators.py` 29/0, `test_module_cache.py` 146/0,
     `test_gimple.py` 354/0, `compile_stdlib.py` 591/19/0.
     (`test_myinterpreter_simple.py`, `test_myinterpreter_validation.py` and
     `test_dispatch_phase_c.py` fail on this tree for PRE-EXISTING reasons —
     the first two on the dead `mojo/ast_nodes.mojo`, the third on
     `DispatchSolver should have been instantiated` — verified by stashing the
     change and re-running.)
3. **Dependent return types**, for the ones that then survive selection:
   `peekable(list)` → `_PeekableIterator[type_of(iterable).IteratorOwnedType]`,
   with `List.IteratorOwnedType = _ListIterOwned[Self.T]`
   (std/collections/list.mojo:361) → `_ListIterOwned[Int64]`. Read the struct's
   own `comptime Name[...] : Trait = <expr>` from its defining module. Do NOT
   textually substitute `Self.<comptime member>` — commit ae8f0493 substitutes
   `Self.<TYPE PARAM>` only, and that scoping is right.
   `_refine_generic_return_type` (mojo/middle/resolve_shared.py:1453) is the
   hook: it re-resolves a return annotation with the struct-aware
   `gen._resolve_type` after substituting mangled type args, but it does NOT
   receive the call's argument types, which this needs.
4. **Overload dispatch outside the iteration protocol** — the 11-file table
   above. Each row is `error: passing argument N of '<Struct>_..._m_hash'`, i.e.
   a call site still holding the erased view beside a definition with the real
   one. Same one-way information loss as `FormatStruct`'s two `fields`, and it
   wants the call site's real argument inference, not another naming change.

**0. `monomorphize.mangle` was not injective — LANDED 2026-10-03.** This is the
"the root cause is `mangle`" claim the reverted experiment below rested on, so
it is worth stating precisely what was and was not true.

`mangle` was `'_'.join(safe_suffix(str(type_args[k])) for k in sorted(type_args))`
— the parameter VALUES joined under `_`, with no key names and a LOSSY escape
(`safe_suffix` mapped every non-alphanumeric char, `_` included, to `_`). Two
independent collisions, measured over the same 1752-pair corpus:

```
mangle('Box', {'T': 'A_B'})        == mangle('Box', {'T': 'A', 'o': 'B'}) == 'Box_A_B'
mangle('Box', {'T': 'List[Int]'})   == mangle('Box', {'T': 'List_Int'})     == 'Box_List_Int_'
mangle('Box', {'T': '_'})          == mangle('Box', {'T': ' '})            == 'Box__'
```

1512 of 1752 pairs collided; after the fix, 0 of 19,676. So the "parameter
NAMES" framing in the reverted-experiment section below was wrong — name
collisions were not the mechanism — but ambiguous segmentation and a lossy
escape were, and either is enough for two different instantiations to share a C
symbol.

`elaborate.Elaborator.elaborate_overload_call` had the same defect on a second
spelling (`safe_suffix('_'.join(ptypes))`); it now uses the same
length-prefixed encoder (`monomorphize.mangle_signature`). Everything this
invalidates is enumerated and measured in
`bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`'s
"Landed 2026-10-03" section: 21 lines of `std/math/math.mojo`'s generated C
change, every one a single symbol rename, and renaming those 8 symbols back
reproduces the old file byte for byte.

**What landing it does NOT establish, stated because it is the obvious next
inference and it is not verified:** that the five `conflicting types`
regressions are gone. `conflicting types for '<name>'` is a statement about a
DEFINITION's real parameter types sitting beside a DECLARATION's erased ones.
Injectivity removes one way to create that (two templates landing on one name);
whether it was the cause is settled by landing in-TU and re-running the sweep,
not by the fact that the name is now unique.

**1. The instantiation TU and its caller named the same function differently —
so nothing this compiler had ever materialized could link.**
`monomorphize.instantiate` built the monomorphized TU with
`module_name=mangled`, and a struct method's C symbol is
`{home-module}_{Struct}_{method}{overload_suffix}`, so it emitted

```
MoveOnly_Int64_MoveOnly_Int64___eq__      <- what the TU defined
MoveOnly_Int64___eq__                    <- what the caller declared
```

The caller has no module identity for a materialized generic struct (no
`_imported_struct_home` entry), so it has no qualifier. Verified by linking
`test/collections/test_array.mojo`'s generated C against its own CAS
instantiation object: `ld: undefined _MoveOnly_Int___eq__`. Fixed by building
the TU with `module_name=''`, the existing convention for "no module identity"
(`_struct_method_qualifier`'s own docstring). The top-level function is
unaffected — it is protected by `no_mangle`, and `empty_Int` measures identical
before and after. This is invisible to every check the project runs, because
`compile_stdlib.py` is `gcc -fsyntax-only`.

**2. The elaborator now READS the TU's symbols instead of composing them.**
`elaborate.elaborate_generic_struct` returns `symbols` (via `nm`, the tool
`build_stdlib_dylib._defined_symbols` already depends on), and
`_register_generic_struct` registers each method under the name the object
ACTUALLY defines. That converts the "duplicate method name disqualifies the
struct" rule from an inference into a measurement: `_Empty[T]`'s two `__iter__`
overloads are reported as `_Empty_Int___iter___0120be` and `_0120be_2`, and
because neither is the bare `_Empty_Int___iter__` a caller composes, the
caller has nothing to dispatch to and the struct is refused — which is the
honest state, and is now demonstrably so rather than merely asserted.

**3. `_struct_name_of` was being used as an "is this a struct?" test.** It is a
pure spelling operation — it strips `const` and the pointer star, so it answers
`'int64_t'` for `'int64_t'`. The `next()` struct-protocol branch used
`if _struct_name_of(_rit):` to decide "`__iter__` returns a different iterator
type", so an `__iter__` whose erased return type is the scalar `int64_t` read as
"yes" and the branch then dispatched `__next__` on `int64_t`. It is now
`_struct_ptr_name`, which requires a trailing ` *`, excludes `_TYPE_MAP`'s
scalar newtypes, and asks `struct_field_types`. **This hid the
already-landed struct-protocol branch from exactly the family it was written
for** — the branch could only ever have been exercised by a struct whose
`__iter__` returns another struct.

**4. Also landed, smaller:** a generic struct with NO FIELDS registers like any
other (`struct _Empty[T]` has none, and refusing it on that ground alone is
what kept `var it = empty[Int]()` typed as a boxed `int64_t`); a generic's
RETURN annotation is now materialized the way a FIELD annotation already was
(`_refine_generic_return_type`'s new `materialize` hook, with
`_register_generic_structs_named` making the returned struct discoverable when
the importer never names it); and the `next(...)` refusal names the RECEIVER'S
C TYPE, because "no lowering for `next(IdentExpr)`" says the shape is
unsupported when the real question is always "why did the receiver not type as
a struct?".

Pinned by `test_module_cache.py::test_generic_instantiation_symbol_agreement`
(11 checks).

### The experiment that was reverted, and what actually blocked it

**In-TU instantiation is the right architecture. It is now LANDED, scoped, and
measured** — see the Status section above for the shipped version, the three
files it fixed, and the two defects it uncovered on the way. What follows is
the record of the first attempt, kept because the next session should not
rebuild it and because its recorded root cause was WRONG in a way worth
remembering.

`mojo/backend_gimple/elab_intu.py` (the first version) monomorphized to SOURCE,
parsed, spliced into `imported_stmts` AND the module's own `stmts` before
struct registration, rewrote the monomorphized return annotation to the
concrete struct name, and registered the spliced function in `_extra_no_mangle`.
With it, **`test/iter/test_empty.mojo` compiled and LINKED**.

It was reverted because it **regressed five currently-compiling files**
(`std/builtin/tuple.mojo`, `std/collections/string/string_span.mojo`,
`std/python/_cpython.mojo`, `std/python/python_object.mojo`,
`test/builtin/test_comparable.mojo`), all with `error: conflicting types for
'<name>'` — an in-TU DEFINITION with real parameter types beside an elaborated
EXTERN with the elaborator's erased ones.

The cause was assumed to be `monomorphize.mangle`, and that assumption was
partly wrong. It did not "key only on the sorted bracket-parameter VALUES, so
two different templates selected for the same call mangle two DIFFERENT
functions to ONE name" because of parameter NAMES: `{T: Int64, o: MutOrigin}`
and `{T: MutOrigin, o: Int64}` are one dict, and as distinct pairings they are
distinct instantiations the old code named differently. What it really did was
join the values under `_` with a LOSSY escape, so `{'T': 'A_B'}` and
`{'T': 'A', 'o': 'B'}` — and, with no segmentation involved at all,
`{'T': 'List[Int]'}` and `{'T': 'List_Int'}` — were one symbol. **That is
fixed and measured (see Status item 0).**

**And fixing it did NOT remove the `conflicting types`** — that is the
correction that matters. Those five regressions came from the two routes BOTH
claiming one instantiation; the shipped version removes the second claim by
suppressing the `.o` route for anything the pre-pass already defines, and the
sweep now reports **zero** `conflicting types` across 591 files. Two feature
narrowings had also been tried and each removed some of the five without
removing all (refusing an OVERLOADED name fixed `tuple.mojo`; refusing a name
the CALLING module defines itself fixed none) — the shipped version refuses on
a MEASURED property instead, and refuses by leaving the `.o` route in charge
rather than by emitting a second definition.

## What it looks like

`next(obj)` where `obj` is a user-defined iterator struct — Mojo's spelling of
Python's `next(obj)` = `type(obj).__next__(obj)`, with the method named
`__next__`:

```mojo
var list = [1, 2, 3]
var iter = peekable(list)     # a _PeekableIterator
assert_equal(next(iter), 1)
```

compiles to a call to a `next` symbol that does not exist:

```c
_t4 = next (_t3);
```

`next` is declared once, variadic, and never defined
(`mojo/backend_gimple/module_gen.py`: `'next', 'int64_t next(...);'` with a
`FIXME:` on the line). So the failure is not a compile error — it is

```
Undefined symbols for architecture arm64:
  "_next", referenced from: ...
```

at LINK, attributed to whichever function happens to contain the call.

The `for` loop over the SAME object is no better. Measured on
`test/iter/test_peek.mojo` at the parent commit: **3** calls to an undefined
`next` and **23** `mojo_unsupported_iter` sites in one generated file.

## Why it was green

`compile_stdlib.py` (the `stdlib-syntax` gate step) is a **syntax** check:
`compile` then `gcc -fgimple -fsyntax-only`. Nothing in it looks at whether
the emitted C is *usable*, and the `test/` tree is not linked by anything.
So 21 stdlib files reported PASS while carrying this. They are listed in
`compile_stdlib.py`'s `EXPECTED_FAILURES` now, with the reason.

The 21: `std/collections/string/iterators.mojo`,
`std/itertools/itertools.mojo`, `test/collections/string/test_iterators.mojo`,
`test/collections/{test_set,test_span}.mojo`, seven `test/iter/test_*.mojo`,
eight `test/itertools/test_*.mojo`, `test/python/test_python_object.mojo`.

**Two of those entries were dead.** `test/itertools/test_chain.mojo` and
`test/itertools/test_peek.mojo` had moved to `test/iter/`, so their entries
named files this sweep never attempts — and a vanished file can never be
observed going green, so nothing reported them. `compile_stdlib.py` now
computes `GONE EXPECTED_FAILURES entries` on a full sweep (the set difference
against the swept paths, alongside the existing `STALE ... now passing` check)
and exits non-zero on it, because a declared red that describes nothing is a
worse hole than one that describes a real bug. Both dead entries are removed;
the files' current paths were already listed.

**And `exit 0` with 21 `...FAIL` lines on screen is not a bug.** `main()` exits
non-zero on `unexpected_failed`, on `stale_expected`, and now on
`_gone_expected`. Verified by deleting one live entry: the same run then
prints `UNEXPECTED failed files:` and exits 1. A `FAILED: 21 (21 expected, 0
unexpected)` summary is the `expect=` mechanism working, and the per-file CAS
cache is a separate axis again — this step re-runs real codegen and a real
`gcc` on a CAS miss, so a 1.4 s green is a warm cache, not a skipped check.

## What is fixed

Three things, all of which turn a silent wrong artifact into a named failure
or correct the substitution underneath it.

**1. `_lower_call` refuses a `next(...)` that matched none of its forms**,
instead of emitting the call to a symbol that does not exist
(`mojo/backend_gimple/emit_calls.py`). That is what made this visible: the
21 files above moved from a false PASS to a named, diagnosable refusal. The
same refusal is what caught this compiler's own `next(iter(_seen))` in
`_lower_call` — a link error thousands of lines from its cause, in the
`fire1` build.

**2. `_lower_call` has a real lowering for the shape whenever the receiver's
type IS resolvable**: `next(<struct>)` → `{Struct}___next__(obj)`, resolving
`__iter__`'s possibly-different iterator type first, exactly as
`emit_loops._gen_for_struct_iter` does. So a struct whose type the codegen
knows compiles for real now. Verified on a non-generic two-struct case
(`struct It` with `__next__`, held by `struct Box`): emits `It___next__`.

**3. `monomorphize_source` substitutes `Self.<param>` as a unit**
(`monomorphize.py`), in a pass that runs before the bare-word one so the
`Self.` qualifier is dropped with the name it qualifies. `Self.T` inside
`struct Box[T]` is the enclosing type's own name for the parameter, so for
`Box[int64_t]` it denotes exactly `int64_t`; the bare-word pass alone could
only rewrite its `T` and leave `Self.` glued to the argument, producing
`Self.int64_t` — a member name that means nothing, which `_mojo_type` then
answered as `int64_t`. That silence is what boxed every generic iterator's
inner field (`_PeekableIterator[InnerIterator]`'s `var _inner:
Self.InnerIterator`, `_TakeWhileIterator`'s, `_FlattenIterator`'s, …), so
`next(self._inner)` inside those monomorphized methods had no receiver type
even once the struct WAS instantiated for a concrete type argument. Pinned by
`test_module_cache.py::test_self_qualified_type_param_substitution` (8 cases,
including the nested-shadowing span rule and a struct-typed argument).

Its supporting half: `elaborate_generic_struct` now also publishes each field's
RAW Mojo annotation (`info['anns']`), and `_ensure_generic_struct` resolves
those through `gen._resolve_type` — the one resolver that consults this
compile's `struct_field_types` — after materializing any generic-struct
instantiation the annotation names into its concrete mangled name
(`_materialize_generic_struct_mentions`). Without it the caller registered
`<inner> *` while `elaborate._struct_layout` — a stateless `_mojo_type`, with
no access to that registry — registered the same field boxed, i.e. the two
sides of the same struct disagreed about its layout.

**No behaviour regression**: `compile_stdlib.py` is 589 passed / 21 expected /
0 unexpected both before and after, and the shape that motivated #3
(`Wrapper[Inner[int64_t]]` whose method calls `next(self._inner)`) fails
IDENTICALLY before and after — the `next(...)` refusal already blocked it, so
#3 is a prerequisite, not a partial version of the fix.

**4. The struct-protocol method symbols compose through ONE composer, across a
module boundary.** A user-defined iterator struct reached through
`from mod import Struct` spelled its protocol methods' C names with a
hand-written `{Struct}___{method}__` f-string instead of
`gen._struct_method_csym`, so the home-module qualifier was dropped and the call
went to a symbol nothing defines (which gcc's implicit-declaration fallback then
typed as `int`, i.e. a wrong POINTER rather than a missing symbol).
`emit_loops._gen_for_struct_iter` (all three of `__iter__`, `__has_next__`,
`__next__`) and `_lower_call`'s `next(<struct>)` branch both did this. This is
what makes "a struct whose type the codegen knows" — item 2's precondition —
mean the same thing in either module. Pinned by
`test_gimple_runner.py::cross_module_iterator_struct_protocol_symbols`.

**5. `for` over a struct with `__next__` and no `__has_next__` is now loud.**
It used to lower to `cond = 0` with a `/* TODO: no __has_next__ */` comment: the
body runs zero times, silently, exit 0. It calls the same
`mojo_unsupported_iter` every other unsupported iterable gets, which names the
type, the reason and the loop's file:line. Pinned by
`test_gimple.py::test_next_on_a_user_struct_lowers_and_its_for_loop_says_why_not`,
which is also the test for item 2's own claim that it compiles AND runs.

## What the remaining blocker actually is

Measured 2026-10-01 on `test/iter/test_peek.mojo`, which is the smallest
member of the family. The receiver's type is `int64_t` because **`peekable` is
never elaborated** — not because its return type is mis-substituted.

Three independent measurements, in order:

1. **The callee is deliberately not an export.** `reflect.collect_exports_src`
   drops every generic template, and `reflect.export_exclusions` on
   `std/iter/__init__.mojo` returns exactly
   `['_ChainedIterator', '_Empty', '_Enumerate', '_MapIterator', '_Once',
   '_PeekableIterator', '_ZipIterator', 'chain', 'empty', 'enumerate', 'iter',
   'map', 'next', 'once', 'peekable', 'zip']`.
   `module_loader.load_module('std.iter')` accordingly returns 14 exports and
   no `peekable`. This is intentional (ELABORATION.md): a generic has no single
   concrete symbol, so importers are supposed to instantiate it on demand.

2. **Nothing instantiates it.** Compiling the file with the `next` refusal
   stubbed out — a throwaway probe, not a candidate fix — succeeds, and the C
   contains no `_PeekableIterator` definition and this call:

   ```c
   #ifndef peekable
   extern int64_t peekable (...);  /* from std.iter */
   ...
   int64_t iter;
   ...
   _t2 = peekable (list);
   iter = _t2;
   _t6 = _t5;  /* int64_t.peek() stubbed */
   ```

   So the artifact that would pass this gate is a call to a symbol nothing
   defines, plus a boxed integer where the iterator is. **Making these 21 files
   go green without fixing the type inference would convert an honest red into
   a false green** — which is why the refusal stays and the fix is not a
   lowering.

3. **The demand-driven elaborator cannot reach `peekable` either.** The call
   site does register the overload set (`_imported_overloads['peekable']`,
   because `std/iter/__init__.mojo` really does declare `def peekable` twice),
   so `_lower_call` does call `_elaborate_overload_call`. It returns `None`,
   at `Elaborator.elaborate_overload_call`'s own no-match bail:

   ```python
   arg_mojo = [c_to_mojo(ct) for ct in arg_ctypes]   # ['MojoList *'] -> ['Int']
   for src, ptypes, ret in overloads:
       if ptypes == arg_mojo:                        # ['Some[Iterable]'] / ['Some[IterableOwned]']
   ```

   The two overloads are distinguished only by a TRAIT BOUND (`Some[Iterable]`
   vs `Some[IterableOwned]`), which `c_to_mojo`'s scalar table cannot answer,
   so nothing matches and the elaborator declines — correctly, since it must
   not silently pick the first.

   And were it to match, it would not be enough: the chosen overload's return
   type is `_PeekableIterator[type_of(iterable).IteratorOwnedType]`, which
   depends on the ARGUMENT's type, and `elaborate_overload_call` compiles the
   renamed function standalone via `monomorphize.compile_fn` — a body of
   `return {iter(iterable)}`, where `iter` is itself an excluded generic. The
   elaborator's model has no notion of a dependent return type.

So the work is, in order:

1. **Overload selection on trait conformance**, not on scalar parameter
   types: pick between `Some[Iterable]` and `Some[IterableOwned]` from what
   the argument's type actually conforms to (`Elaborator.check_conformance`
   and `Some[...]` already exist; `_C_TO_MOJO` is the table that has to learn
   to answer a conformance question instead of a ctype).
2. **Dependent return types**: resolve `type_of(<arg>).IteratorOwnedType`
   against the argument's concrete type, so `peekable(list)` is
   `_PeekableIterator *` in the caller. That needs the argument's
   `IteratorOwnedType` to be known — which means the callee's `Self.<member>`
   comptime members have to be resolvable too, and they are NOT type
   parameters (fix #3 above is deliberately scoped to type parameters and
   leaves `Self.Element`, `Self.IteratorOwnedType`, `Self._OuterProduct2Type`
   alone, since substituting those would be wrong).
3. **Materialize the returned generic struct in the CALLER** — the elaborated
   `Inner_int64_t` plus the methods `next` needs (`__next__`, and `__iter__`'s
   possibly-different type, which `_lower_call`'s struct-protocol branch
   already resolves) — so `func_return_types` carries `<mangled>___next__` and
   the existing struct-protocol branch takes over with no further change to
   `emit_calls.py`.

Until all three land, `next(<user struct>)` on an un-inferred receiver must
stay a refusal: the alternative is the silent wrong artifact, which is strictly
worse and is what this project has been removing one shape at a time.

## Next step

**Nothing about the wiring is left; what remains is the type-argument inference
and the mangling collision described above.**

For the family itself, the two cheapest members first: `once(10)` and
`repeat(42, times=3)` take their type argument from a LITERAL, whose Mojo type
is exact rather than inferred, so they need no bidirectional inference at all —
only for the elaborator to read the literal's type where the argument
expression sits instead of requiring it to be written in brackets. Then
`chain(l1, l2)` needs `IterableType` from a container's element type
(`MojoList *` carries it in `gen._elem_types`) and the DEPENDENT return
`_ChainedIterator[A.IteratorType[origin], B.…]`. That associated-type
resolution is bounded and mechanical — read `comptime Name[...] : Trait =
<expr>` from the struct's own source and substitute its type parameters
(`List.IteratorOwnedType = _ListIterOwned[Self.T]` → `_ListIterOwned[Int64]`,
`std/collections/list.mojo:361`) — and it is the same layer `size_of[T]()`'s
use-site inference needs, so build it once, here, and share it.

Before either: **land in-TU instantiation with ONE template selection shared
between the pre-pass and the demand-driven route** (see the reverted experiment
above). It is the only route that can serve this family at all — measured, EVERY
iterator struct in `std/iter` overloads `__iter__` on `var self` / `ref self`
(`_Empty`, `_Once`, `_PeekableIterator`, `_MapIterator`, `_ZipIterator`,
`_ChainedIterator`, `_Enumerate`), both overloads erase to `(Struct *)`, and so
`_register_generic_struct` cannot know which of the object's two suffixed
`__iter__` symbols a call site means. That is the same wall `FormatStruct`'s two
`fields` hit, and in-TU is where the host codegen names its own methods
correctly and consistently instead.

**Gate every step on the artifact, not on the gate step.** `compile_stdlib.py`
is `gcc -fsyntax-only`: it cannot see a call to a symbol nothing defines, and
this file's entire history is that history. For each file removed from
`EXPECTED_FAILURES`, require that the module's own object DEFINES the
instantiation and its `__next__` (`nm -g` after a real `gcc -c`) and that a
real link leaves no undefined symbol for it. All three defects in this
session's Status section were found exactly that way and by nothing else.

**Scope note, measured 2026-10-02.** The "424 sites / 157 names / 194 files"
figure quoted elsewhere in this file is the mis-measurement this document's own
Status section corrects; the census reads **96 sites / 51 names / 60 files**,
and it did NOT move in this session — expected, and worth stating rather than
hiding: the census only counts files that COMPILE, and these 22 do not, so the
two populations are disjoint. `FormatStruct` (15), `alloc` (10) and
`ThinAllocation` (8) remain the census's largest names and are untouched by
this work; see `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`.
