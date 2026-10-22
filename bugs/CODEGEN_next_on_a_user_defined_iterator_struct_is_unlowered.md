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

### Landed 2026-10-20: the nested-struct materialization blocker is closed,
measured — the remaining work is the call itself

The one blocker that stood between the fixed receiver half and the family's
own materialization was the NESTED generic-struct type argument:
`_PeekableIterator[InnerIterator]` instantiated for
`_ListIter[True, Int, ImmOrigin, True]` refused in the isolated
monomorphized TU — the nested mention has no registration there, so the
by-value field `var _inner: Self.InnerIterator` erased to `int64_t` and the
wrapper's own `next(self._inner)` hit the dead-end refusal (measured before:
`RuntimeError: next(...) on next(MemberExpr) (receiver typed int64_t) has no
lowering`, emit_calls.py:1772). It is fixed and measured:

- `monomorphize.instantiate(nested_defs=, renames=)` splices the nested
  struct's own monomorphized definition (fields + methods, already renamed
  to its mangled name) AHEAD of the template in the isolated TU, and rewrites
  each nested mention in the template (and the nested defs) to the mangled
  name — longest-mention-first so `A[B[C]]` matches whole. Both fold into the
  CAS key under a distinct `mojo-inst-v2-nested` domain, so a nested
  instantiation can never collide with the plain one and no plain
  instantiation's key moves.
- `elaborate.elaborate_generic_struct(nested=)` bound-checks and
  monomorphizes each nested struct and passes the splice through.
- `module_gen`'s field-annotation pass resolves a bare annotation that is a
  REGISTERED struct name under a non-capitalized spelling (mangled private
  instantiations, `_ListIter_1_T_3_Int_...`) to the pointer spelling — the
  capitalized-only test skipped them and the field sat at `int64_t`.
- `monomorphize_source` no longer lets a type parameter spelled like a
  receiver convention rewrite the receiver marker: `_ListIter[mut: Bool, ...]`
  substituted the `mut` of `def __next__(mut self)` into `True self`, giving
  the method an EXTRA parameter — gcc then rejected the caller's one-argument
  `next(<struct>)` call ("too few arguments... expected 2, have 1"). The
  `<param> self` position is excluded, and the guard is folded into the CAS
  key so any pre-fix cache entry for such a template (only `_ListIter` in
  stdlib) is rerouted to a fresh build.
- `emit_methods._lower_struct_method_call` re-keys `_return_slot_types` onto
  the call result (the twin of the existing `_return_elem_types` re-key;
  `_lower_named_call` already had it for bare-name calls). Without it, a
  struct method returning a HETEROGENEOUS tuple — `_ListIter.bounds` ->
  `(iter_len, {iter_len})` — unpacked at the caller with the JOINED elem
  type, so `var lower, upper = self._inner.bounds()` read slot 0 as `MojoSet
  *` and `lower + peek_len` became pointer arithmetic over an incomplete
  type: a hard gcc error, an ICE under -fgimple (tree.cc:5208) — the same
  failure the return-side recording at emit_stmts.py documents.

Measured after: `elaborate_generic_struct(iter_src, '_PeekableIterator',
['_ListIter[True, Int, ImmOrigin, True]'], nested=[...])` BUILDS — CAS .o,
13 symbols (the nested `__iter__`/`__next__`/`bounds` plus the wrapper's
`__init__`/`__iter__` x2/`__next__`/`bounds`/`peek`), and the generated C
typedef is `{ __mojo_type_id; _ListIter_... * _inner; int64_t _next; ... }`
— the pointer spelling per this codegen's universal struct-as-pointer
convention. The standalone `_ListIter` materialization regressed in the
GOOD direction: `__next__`'s parameters are now `[]` (receiver only), was
`['int64_t']` (the corrupted extra parameter).

The sweep is UNCHANGED at 592 / 18 / 0: the materialization is the
infrastructure; the 17 files still fail at the CALL, which is the next
piece, in order:

1. **Overload selection** — the two `peekable` overloads are distinguished
   by PASS MODE (param `ref` vs `var`/moved) with conformance (declared
   trait list) as the gate; `List` declares BOTH `Iterable` and
   `IterableOwned`, so conformance alone cannot disambiguate. Site:
   `elaborate_overload_call`'s exact-string match (elaborate.py:1010).
2. **Dependent return** — evaluate `type_of(arg).IteratorType[origin_of(
   arg)]` against the concrete arg type: `List`'s `comptime IteratorType`
   is the AST of `_ListIter[downcast[Self.T, Copyable], iterable_origin,
   True]`; `downcast`/origin terms are C-erased; the resulting mention then
   goes through `elaborate_generic_struct(..., nested=[...])` — which now
   works (above).
3. **Call-site construction** — the specialized body `return
   {iter(iterable)}` lowers to a bare identity in isolation; the call site
   must emit the container's own iter construction (list.mojo:710:
   `_ListIter(0, self.unsafe_ptr(), self._len)`), then the wrapper's
   `__init__(out self, var inner)`, and return `P *` — after which
   `next(it)` / `it.peek()` / `it.bounds()` resolve through the existing
   struct-protocol branch.
4. **Registration layout** — the caller-side report still says
   `('_inner', 'int64_t')` (`_struct_layout_anns` analyzes the un-renamed
   outer source); the outer compile's P registration needs the mangled-name
   mapping when the call site wires up.

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
      `CODEGEN_reexported_function_import_qualifier_names_the_wrong_module`
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

## 2026-10-20 (continued): the call-site mechanism was built and measured,
then refused itself — a false green averted, a regression caught, a net-zero
session with the next project scoped

### What was built, and that it works at the call site (measured)

The dependent-return iterator-factory mechanism landed in three places:
`mojo/middle/iter_factory.py` (new — pure analysis: container resolution
incl. `List[T]()` ctor calls and `BoolLiteral` elements, call keys),
`elab_intu._seed_factories` / `_seed_one_factory` (finds every factory call
site, evaluates it, files the record and enqueues the wrapper), and
`emit_calls._lower_factory_call` (container -> inner ctor -> wrapper ctor;
`count=`/`start=` kwargs; nested factories by recursion). Four support fixes
came with it: the owned ctor taking any pointer ctype while the borrowed
path stays `MojoList *`-only; the `struct_field_types` PRE-REGISTRATION of
every materialized struct's mangled name before the statement loop (the
wrapper `__init__` param annotation otherwise erases to `int64_t` in the
pre-statement signature passes); and the suffixed `func_param_types` mirror
in the module_gen refresh pass.

The call-site half is measured WORKING in the generated C for all five target
shapes (session log `c_test_{peek,enumerate,take,drop}.c`, `c_userstruct.c`):
wrapper/inner construction, the moved/borrowed overload pick
(`peekable(l^)` -> `_ListIterOwned[Int]`, `peekable(l)` -> `_ListIter[Int]`),
and the nested-factory recursion (`take(take(nums, 4), 2)`) all lower to real
mangled symbols with real definitions. `test_cycle` resolves 16/18 sites;
the 2 remaining (`cycle(_owned3(1, 2, 3))`, `cycle(_owned1(42))`) pass a
user-defined `IterableOwned` struct — a SECOND blocker (local
comptime-parametrized materialization is non-mangled; local-fn returns box to
`int64_t`; the R2 local-generic-elaboration sibling).

### Why it refused: the in-TU data path is unlowerable (measured)

The four "green" Stage A files were FALSE GREENS. The gate
(`gcc -fgimple -fsyntax-only`) cannot see any of this, and nothing else
links the `test/` tree; the generated C says it all:

- `int64_t_unsafe_offset` — called by the in-TU `_ListIter*___next__`
  element path — is a DECLARATION-ONLY stub; no definition exists anywhere
  in the repo.
- `int64_t.unsafe_take_pointee()` is 0-stubbed (no dereference).
- LAYOUT MISMATCH: the formal in-TU `List_1_T_3_Int {__mojo_type_id,
  _storage, _len}` vs the runtime object `MojoList {data, len, cap, inl}` —
  the body's `_list->_len` reads offset 16 (the runtime's `cap`), and
  `unsafe_ptr` reads offset 8 (the runtime's `len` reinterpreted as a
  pointer).
- `List[Int]()` lowers to the in-TU shell allocator plus an in-TU
  `__init__` whose storage allocation is 0-stubbed (`_storage = 0`).
- Subscript reads emit `List_1_T_3_Int___getitem__(...)` — another
  declaration-only varargs stub.

The mechanism now REFUSES to fire for List containers:
`elab_intu._seed_one_factory` files no record when `cont['kind'] ==
'list'`, with the measured evidence as the comment at that site (do not
remove without re-measuring). Call sites keep the baseline
`next(<int64 box>)` refusal, so the five files stay DECLARED red in
`EXPECTED_FAILURES` (shared `_FACTORY_DATA_PATH` reason constant) — and no
in-TU `List_1_T_3_Int` exists anywhere, which is what kills the regression
below.

### The regression the same measurement caught, and its fix

With the mechanism live, TUs that seed the BUILTIN `iter`/`enumerate`
HIJACKED the container representation to the in-TU List shell:
`test/collections/test_list.mojo`'s subscript store raised at codegen, and
`test/random/test_random.mojo` likewise — the sweep went 594/16 with 2
UNEXPECTED failures. The refusal removes every in-TU List: both files' C is
again the runtime-`MojoList` representation with 0 `List_1_T_3_Int`
references, real `mojo_list_set_int`/`mojo_list_get_*` calls, and both
re-gate exit 0 in the final code state (session log
`c_test_list_fixed.c` / `c_test_random_fixed.c`; re-verified byte-identical
after every later code change).

### Full-tree A/B: the true baseline, and what actually changed

Method correction (measured): the 05:02 `c_hashes_baseline.tsv` was a
MID-SESSION snapshot (mid-edit working tree), not the before-state. The true
before-state is clean master, taken via a git worktree at c947025a.
Cross-process determinism was verified first (a `c_hash_all` rerun is
byte-identical; per-file hashes are identical across fresh processes).

**Cross-module contamination is real and measured**: compiling multiple
files in one process — or via the 12-worker pool with its file-dependent
worker assignment — changes the generated C; module-level state persists
across files. A sequential multi-file loop of 7 files produced a 7-file
diff; the same 7 files in fresh processes showed 4 of them byte-identical
between the trees. The only trustworthy per-file shape is a fresh process
per file; the pool shape is reproducible (same run, rerun byte-identical)
and is what the sweep uses, so pool-vs-pool A/B remains valid for
file-set-level conclusions — just not for byte-level per-file claims.
(Also cost an hour: `dict.setdefault` and C-level dict ops bypass
`__setitem__` overrides on dict subclasses — a tracer that only wraps
`__setitem__` misses them; the `_Empty` trace went blind exactly there.)

The TRUE pool A/B (all 610 files, clean master vs working tree, pre-fix)
changed exactly 3 files — `test/iter/test_empty.mojo`,
`test/iter/test_once.mojo`, `test/itertools/test_repeat.mojo` — with zero
C<->ERROR transitions. Fresh-process scrutiny of those 3 (and of the 4
earlier-contaminated files, all byte-identical) showed the 3 differ in
exactly ONE thing: the in-TU iterator stub struct loses its `int64_t copy`
field (emitting `int _dummy` instead) and the whole reflection dispatch
(`_known[] = {1680525625}` -> `{0}`; the getattr/fieldnames/repr shims
disappear).

**Root cause (measured with temporary prints, since removed):** elab_intu's
pre-registration lands in `gen_module_impl`'s
`_selfhost_hardcoded_struct_names` snapshot (module_gen.py:4746 — taken
after `elab_intu.run()` at :3411, before the statement loop), and that set
EXCLUDES its members from the read-field pass (module_gen.py:5903) and the
local-annotation pass (module_gen.py:6023). The `copy` field is what the
read-field pass mints from `self.copy()` in `__iter__(ref self)`
(std/iter/__init__.mojo:301, base lookup through the `ImplicitlyCopyable`
protocol). One node, owner, 4 methods — verified single-node; the skip fired
at the hardcoded-name guard, not a double-registration.

**Fix (measured, in place):** pre-registration records the names it ADDS in
`gen._intu_prereg_structs`; the 4746 snapshot excludes that set. The early
name resolution the pre-statement signature passes need stays; the
read-field/local-annotation passes behave exactly as on clean master.
Post-fix, in order: fresh-process A/B on the 3 files byte-identical (hashes
equal to clean master's); full-tree POOL A/B 0 diff lines across all 610
files; sweep 592/18 EXIT 0 (the exact baseline set, 18 expected, 0
unexpected — `sweep_after_fix.log`); the 3 files' C directly re-gated
(`gcc-mp-15 -fgimple -fsyntax-only -I runtime -D__MOJO_STDLIB_MODE__`,
exit 0). The full-tree generated C is now byte-identical to clean master in
both run shapes.

**Note on the sibling doc.** `CODEGEN_imported_generic_never_elaborated_
calls_nothing_defines.md`'s "Landed 2026-10-20" 4-file A/B table was
measured against the mid-session 05:02 snapshot; against the true
clean-master baseline those 4 files are byte-identical in both run shapes.
See that doc's "2026-10-20 (continued)" correction.

### What this session moved, honestly

**Zero files out of `EXPECTED_FAILURES`** — baseline 592/18 in, 592/18 out,
the identical 18. What it left: a working, measured call-site mechanism,
dormant behind an honest refusal whose comment IS the measurement; the
regression caught, fixed and re-verified; the full-tree C byte-identical to
clean master in both run shapes; and the A/B methodology corrected (true
baseline via worktree, fresh-process per-file scrutiny, contamination
named). That is a zero-movement session that averted a 4-file false green
and a 2-file regression — both of which the old process would have shipped
as green.

### To lift the refusal (the next project, scoped)

Synthesize the in-TU iterator protocol in RUNTIME-LIST terms:
`__init__`/`__iter__`/`__next__`/`bounds` of `_ListIter`/`_ListIterOwned`
as `mojo_list_len`/`mojo_list_get_*` over a `MojoList *`-typed `_list`
field, with the spliced wrapper bodies delegating to it — or implement the
in-TU List storage end-to-end (allocator + subscript). Then verify with the
`gcc -c` + `nm` + `ld` + run ladder (the 2026-10-03 pattern): the module's
own object must DEFINE the instantiation and its `__next__`, and a real
link must leave no undefined symbol. Never the syntax-only gate.
## 2026-10-20 (further): the refusal is lifted — List-container factories
materialize in-TU over the runtime list, value-ladder-verified, 596/14

### What the lift does (measured end-to-end, not gate-only)

The refusal filed in "2026-10-20 (continued)" is gone. The dependent-return
iterator factory now FIRES for `List` containers, and its value is a real,
linkable, runnable in-TU struct:

- The runtime `MojoList *` container is KEPT as the iterable's storage (the
  in-TU `List_1_T_3_Int` shell from the (continued) session — with its
  `int64_t_unsafe_offset` stub, its layout mismatch against the runtime
  object, its 0-stubbed storage — is not used; no in-TU `List_*` struct
  exists anywhere in the generated C, the regression probe from the previous
  session holds).
- `_ListIter`/`_ListIterOwned` are materialized in-TU with RUNTIME-TYPED
  fields (`MojoList * _list`, `int64_t _index`, `int64_t * _data`,
  `int64_t _length`), and their `__init__`/`__iter__`/`__next__`/`bounds`
  bodies are the spliced stdlib bodies REWRITTEN to lowerable expressions
  (`elab_intu._IN_TU_LIST_BASES` 3-site guard + `_IN_TU_ITER_BODIES` +
  `_rewrite_inner_bodies`): `mojo_list_len`/`mojo_list_get_*` over the
  `MojoList *`, exhaustion spelled `mojo_exc_type_set(590612416);
  mojo_raise ()` — exactly the raise protocol the runtime's
  `StopIteration` uses.
- The wrapper (`_Enumerate[...]`, `_TakeIterator[...]`, `_DropIterator[...]`,
  `_CycleIterator[...]`, `_PeekableIterator[...]`, ...) is allocated by a
  generated `_alloc_` (malloc + generated `_init_`), its registered
  `__init__` overload is direct-emitted, and the spliced wrapper bodies
  delegate to the inner.

### The mechanism fixes that came with it (all measured, all in tree)

1. `parse_return` for the factory family: `{'wrapper': None}` — the factory
   RETURNS the inner iterator directly when the wrapper is identity.
2. Bare `iter(<container>)`: the seed enqueues the inner as a root
   (`wrapper=None`) and `emit_calls` returns it directly — 3-part change.
3. **Setjmp raise-exhaustion for-loop** (`emit_loops._gen_for_struct_iter`):
   a `__next__`-only iterator struct cannot test a loop condition (the
   condition IS the call, and only a setjmp region can see the longjmp), so
   the frame is pushed once at entry, `bb_post` loops straight to `bb_body`,
   `break`/`return` are intercepted (`mojo_exc_pop` prepended), and `bb_exc`
   pops + tag-checks `== 590612416` -> `bb_after`, else `mojo_raise()`.
   **Gate (fixed 2026-10-21, see below): trusted only for in-TU
   materialized wrappers** (`iter_base in gen._intu_prereg_structs`).
4. **Wrapper `bounds` branch-folding rewrite**: the inner's `{iter_len}`
   set-literal slot lowers to a RAW WORD (0 == None), so `if upper:` +
   `upper.value()` in `take`/`drop`'s spliced `bounds` must be folded to
   int-truthiness + identity — measured: `test_take_bounds` it4
   `take(empty, 5)` returned `upper=5`, must be 0. `_IN_TU_ITER_BODIES`
   covers the 4 list-backed bases; take -> `return (lower, min(upper,
   remaining))`, drop -> `return (lower, max(0, upper - to_drop))`;
   `_PeekableIterator`/`_Enumerate` bounds delegate (no rewrite).
5. **`.copy()` protocol lowering for in-TU structs** (`emit_methods`):
   registered `__init__` overload set resolved on the `copy` kwarg ->
   alloc + DIRECT ctor emit (NOT `_lower_struct_constructor` — its coercion
   reads `func_param_types`, which at statement-loop emission still holds
   the erased `int64_t` for the `copy: Self` param — measured box + gcc
   int-conversion error); else a synthesized FIELDWISE DEEP copy
   (`_emit_fw_copy`, depth < 4): each field via a temp (GIMPLE rejects
   `component_ref` store RHS), in-TU struct-pointer fields get a fresh
   `_alloc_` + recursive copy. Measured: aliased inner cursors broke
   `test_cycle_copyable` (computed 1 / expected 3); the shared `MojoList *`
   buffer stays shared (real Mojo implicit-copy semantics).
6. **`iter(<in-TU iterator struct local>)` = protocol copy**: real Mojo's
   `iter(x)` calls `x.__iter__()`; for the lifted family the spliced body is
   exactly `return self.copy()`. The old identity echo was a measured
   aliasing bug (`test_cycle_iterator_protocol`). Two sites in `emit_calls`,
   gated `rec['kind'] == 'factory'` + in-TU struct-pointer `inner_t` +
   `IdentExpr` arg — the kind gate is load-bearing (without it
   `iter(<list local>)` echoed the list and broke `test_enumerate_bounds`:
   computed 0 / expected 3).
7. **`comptime assert` no-op** (`emit_stmts._gen_stmt_AssertStmt`): real
   Mojo runs no runtime check; the spliced `_DropIterator.__next__`'s
   `comptime assert conforms_to(...)` was leaking to a value-path branch on
   undefined `conforms_to` + `__builtin_trap` (test_drop link failure
   `_conforms_to`). Compile-time checking is not implemented (honest note).
8. **Function-level import factory homes** (`elab_intu._import_name_map`
   recurses into function bodies; first declaration, outermost-then-source
   order, wins): a function-level `from std.itertools import take`
   (`test_drop_then_take_composition`) previously left the call on the plain
   imported-name path (`extern int64_t take(...)` -> link fail). See the
   R2 doc's "2026-10-20 (further)" for the imported-generic side.
9. **`unsafe_take()` consume** (`emit_methods._lower_method_call` scalar
   region): two-step zero — Gimple requires it (single-expression
   `x = 0; return old` mis-erased).
10. **`ImmPointer[T](to=x)` dual storage shape** (`emit_calls.
    _lower_immpointer_ctor`): measured emission-context rule — inside
    `__GIMPLE`-tagged fns, `&` of local/static/global is ALL rejected
    (gtest1/gtest2.c), so (a) the STATIC word-slot shape
    (`_lk_peekdata`/`_lk_peekview`/`_lk_peekword` function-scope statics,
    two-level P->word->view) ONLY in safe-untagged contexts — gate
    `gen._emitting_plain_func or gen._func_used_setjmp` (a function whose
    body already emitted setjmp is guaranteed untagged; the verified peek
    site is safe via that); (b) HEAP shape everywhere else —
    `mojo_list_new()` + `mojo_list_append_int(view, word)`, the returned
    pointer IS the view list (one allocation, no `&`), matching the measured
    python.mojo accessor contract (`self._impl[]` casts P directly to
    `MojoList *`, no word indirection). The two contracts are mutually
    exclusive per site; each site's consumer was measured. This fix also
    repaired the `std/python/python.mojo` regression the static shape had
    caused there (zero `_lk_peek*` refs in the python TU after; the tag rule
    is `'' if _func_used_setjmp else '__GIMPLE '`).
11. **`with assert_raises():` setjmp frame** (`emit_stmts._gen_stmt_WithStmt`):
    the bare form whose struct has no in-TU `__exit__` lowers to a try-frame
    (body raise -> `mojo_exc_pop(); goto bb_after`; normal exit ->
    `mojo_exc_pop(); assert_raises_no_raise()`). Blast radius ~55 files.
    The `contains=`/error-type matching is NOT verified (documented edge);
    multi-context and `as` forms keep the old lowering.
12. **Ladder module-name bug fix**: `ladder.py` now mirrors the sweep's
    exact module naming (full rel path, `os.sep`/`-` -> `_`) — the mangle
    prefix of every emitted symbol derives from it; the old basename
    spelling produced different C bytes than the sweep gates.

### Value-ladder evidence (real `gcc -c`, `nm -g`, link, run, checked values)

Re-verified 2026-10-21 AFTER every one of the fixes above, fresh process,
sweep module naming:

| file | result |
|---|---|
| `test/iter/test_peek.mojo` | PASS 6/6 — generated C BYTE-IDENTICAL to the previously verified `ladder_test_peek.c` (cmp; the invariant re-holds after the ImmPointer dual-shape change and the 2026-10-21 bucket fixes) |
| `test/iter/test_enumerate.mojo` | PASS 6/6 |
| `test/itertools/test_take.mojo` | PASS 13/13 |
| `test/itertools/test_drop.mojo` | PASS 14/14 |
| `test/itertools/test_cycle.mojo` | RED by design — 15/17 sites work with real values (Int/String/Bool lists, `List[Int]()`, `range(...)`, copyable/iterator-protocol/for-loop/composition forms; scratch copy without the 2 user-owned tests: ladder PASS 15/15). The 2 remaining (`cycle(_owned3(1,2,3))` :283, `cycle(_owned1(42))` :302) hit the local-generic-elaboration refusal `next(...) on next(IdentExpr) (receiver typed int64_t) has no lowering` — the SAME failure surface on clean master (measured in both A/B trees; the message is byte-identical, the mechanism differs underneath). |

### Sweep, warn set, A/B (all 2026-10-21, final code state)

- Sweep: **596 PASSED / 14 FAILED — 14 expected, 0 unexpected, EXIT 0**
  (baseline 592/18). The 14 are exactly the `EXPECTED_FAILURES` set (3
  distinct reasons; see the R2 doc). The warn set is identical to clean
  master and to the pre-lift runs: the same 15 files / 248
  "generic struct elaboration(s) failed … NOT being cached" warnings, file
  for file and count for count.
- Full-tree A/B vs clean master worktree (de890235), BOTH run shapes:
  pool (12-worker, sweep shape): 18 -> 14 errors, 493 unchanged, 4
  ERROR->C (the lifted files), 0 C->ERROR, 113 C->C hash-changed.
  Fresh-process (one interpreter per file, the trustworthy per-file shape,
  610-row TSVs): the SAME 493/4/0/113 split — so the 113 are real
  cross-tree changes, not pool contamination. `test_cycle`'s ERROR row is a
  byte-identical message in both trees. The 113 are the documented blast
  radii of the fixes above (assert_raises frame ~55, setjmp for-loop,
  comptime-assert no-op, `.copy()`, iter-struct copy, ImmPointer heap in
  python.mojo, import map, lift files); the regression probes
  `test_list`/`test_random` are byte-identical (the (continued) session's
  2-file regression stays fixed).

### The bucket regressions the lift exposed, and their fixes (2026-10-21)

The check bucket (`tools/suite.py`) dropped to 51/53; both failures were
measured, not guessed:

1. **`gimple` job — the named refusal was swallowed.** The raise-exhaustion
   setjmp for-loop (fix 3) gated on "`__has_next__` absent + `__next__`
   present", which fires for ANY such struct — including a USER-defined
   `class Counter` with a Python-style `__next__`. test_gimple.py's
   `next_on_a_user_struct_lowers_and_its_for_loop_says_why_not` pins that
   the loop over such a struct is a NAMED refusal (`mojo_unsupported_iter`
   + `Counter (no __has_next__)`) — its docstring: "making the loop actually
   work is the type-inference project the doc parks, and inventing a wrong
   loop here would be worse than both". Fix: the gate additionally requires
   `iter_base in gen._intu_prereg_structs` — the frame is trusted only for
   the codegen's own materialized wrappers, whose raise protocol is spelled
   by this compiler's own `mojo_exc_type_set` + `mojo_raise`; user structs
   keep the named refusal + zero iterations. `test_gimple.py`: 395/395
  EXIT 0.
2. **`gimplerunner` job — the stale pre-pass table meets the wrapper.**
   `z = enumerate([7, 8])` (function scope) declared `z` `MojoList *`
   (the pre-pass's `_BUILTIN_RET_CTYPES` guess — the old materialized
   pair-list model) while the value is the in-TU `_Enumerate_... *`:
   `len(z)` read a struct field as a length (printed `4376269232`),
   `print(z)` walked garbage (printed nothing). The `var`-declared twin was
   already fine (unannotated `VarDecl` trusts the emitted ctype). Six-part
   fix: (a) plain `AssignStmt` first-bind trusts the emitted vtype when it
   is an in-TU struct pointer and the pre-pass said something else;
   (b) `len(<wrapper>)` answers the NON-consuming `bounds()` upper (the
   in-TU `bounds` returns a boxed 2-element tuple list `[lower, upper]`;
   enumerate delegates to its inner list, take's rewritten body answers
   `min(count, remaining)`, drop's `max(0, len - n)` — materializing in
   `len` would consume the iterator, which the bucket's
   `print(len(z)); print(z)` sequence proves wrong); (c) a new shared
   materializer (`emit_infra._materialize_in_tu_wrapper`) consumes the
   wrapper with the exact setjmp frame idiom of fix 3 into a fresh
   `MojoList *` and appends the raw element word — the in-TU `__next__`
   raises by longjmp on exhaustion, so the frame is mandatory; (d)
   `print(<wrapper>)` routes through it and the pair-aware
   `mojo_repr_list_pairs` (the measured baseline spelling for the old
   materialized pair list; `_Enumerate`'s element is a boxed tuple-PAIR
   list, so the materialized list gets `_elem_types = 'MojoList *'` +
   nested `[int64, int64]`); (e) `list(<bound wrapper local>)` materializes
   too (the comprehension route has no in-TU struct-pointer arm and would
   emit an empty list — a regression against the baseline's materialized
   pair list; the inline `list(enumerate(...))` shortcut is untouched);
   (f) module-level `z = enumerate([7, 8])` — the global read-back arrives
   boxed (`int64_t`) with the actual type carried in `_actual_types`;
   `_note_global_store_types` now records the in-TU wrapper vtype directly
   (the `setdefault` kind list is the three runtime containers, and the
   factory temp has no overlay entry), so the read retypes to the wrapper
   and (d) fires. `test_gimple_runner.py`: 461/461 EXIT 0, including
   `gimple_enumerate_value_printed` (`2` + `[(0, 7), (1, 8)]`) and
   `gimple_global_from_enumerate_call`.

3. **`no-new-casts` guard — my own cast tripped the R3 tripwire.** The
   `len` branch of (2b) hand-wrote its `(MojoList *)` reinterpret in an
   emitted-C template string, and `test_no_new_container_casts.py` counts
   exactly those (baseline 17; the guard's text scan deliberately sees
   casts the generated program really executes). Fixed at the chokepoint
   the guard exists to enforce: the branch now calls
   `gen._coerce_to_type('int64_t', 'MojoList *', ...)` (emit_resolve.py —
   the one file the count excludes), which emits the same cast with one
   extra GIMPLE-safe register copy (verified: the normalized generated-C
   diff is that single line plus temp renumbering; gate exit 0). Guard
   back to its baseline 17.

Final bucket state on the complete fix set: `tools/suite.py` **53/53,
exit 0** (51/53 at the start of the session's bucket work; the two jobs
above plus the guard, in order).

Ground truth check for (1)/(2): real stdlib's `_Enumerate` (std/iter/
__init__.mojo:388) has NO `__len__` and NO `__repr__` — the bucket's
`len`/`print` contract is this codebase's own materialized-pair-list model,
and the lift preserves THAT contract through the lazy wrapper, which is
what the pinned tests assert.

### What is NOT verified (honest list)

- `assert_raises`'s `contains=` / error-type matching: the frame verifies
  "raised" vs "did not raise" only.
- `comptime assert`: no compile-time checking is implemented — the
  statement is a no-op, matching real Mojo's runtime behaviour, not its
  compile-time conformance check.
- The materializer's element repr tracking: `_Enumerate` over a non-int
  inner list defaults the pair's second slot to `int64_t` (the tracked
  inner element type is not resolvable at the print site); the bucket and
  the ladders exercise the int case, which is what the baseline pinned.
- `test_cycle`'s 2 user-owned sites remain the local-generic-elaboration
  gap (R2 sibling), unchanged in surface from clean master.

## 2026-10-21: the two home modules lift, the direct-struct factory lifts,
declared-red is 11 with per-file measured reasons

### What changed

1. **Definition-site generic method bodies: the transactional fallback**
   (lifts `std/itertools/itertools.mojo` and
   `std/collections/string/iterators.mojo` — the two HOME modules of this
   family — out of the declared red):
   - `fire_compiler.StructDef` gained `type_param_names` — ALL bracket-block
     names, including the trait-bound ones (the old capture dropped those;
     `bracket_params` is empty for exactly the generic structs, so this
     field is the marker).
   - The measured reason for the home failure stands: a generic struct's
     definition-site body CANNOT always lower — a type-param-typed field
     erases to `int64_t` in the definition TU, so `next(self._a)` in
     `_Product2.__next__` hits the emit_calls hard refusal and the WHOLE
     module failed; the instantiating TU is the one that must emit the
     mangled copy with real field types.
   - **First cut — an unconditional body skip for every type-param struct —
     and why it was wrong** (measured against the de890235 A/B): it dropped
     1,768 definitions, **133 of them referenced from other TUs** — a real
     link hazard: `Span` is generic (`struct Span(Element: Movable, //,)`)
     but its lowerable baseline bodies (`Span_count`, `Span_copy_from`,
     `Span__binary_search_index`, `Span_fill`, `Span_swap_elements`) are
     genuinely CALLED from `_unicode.mojo` / `_utf8.mojo` / `test_span.mojo`
     / `test_span_address_space.mojo` — the skip would have left those
     undefined at link. The skip also silently turned ~107 already-green
     files into churn and broke the warn-set parity (13/244 vs 15/248).
   - **Final design: attempt every body exactly as master did; fall back
     per method.** In module_gen's struct-method loop the emission is
     wrapped in try/except that catches ONLY the codegen's own honest
     `RuntimeError` starting `cannot compile module:` — a refusal, not a
     bug. On a refusal a transactional rollback (the emit_loops
     regex-fallback pattern) restores: func_parts from the pre-call mark,
     the import-scope stack down to its pre-call depth (the method's own
     frame pops with it), `body_lines`/`decls` (cleared at the method's own
     `_reset_func`, so they hold nothing but this method's partial output),
     the annotation-seeded container maps (`_elem_types` /
     `_nested_elem_types` / `_dict_val_types` — the only shared dicts
     `_gen_struct_method` setdefault-seeds per LOCAL name), and the
     line-source override; the method then lands as prototype-only with a
     diagnostic comment. Anything that is NOT a codegen refusal
     propagates, exactly as master would have. Result: every LOWERABLE
     body emits byte-identical to master (span.mojo's after-C is
     byte-identical to the Part 1 tree — the only residual vs-baseline diff
     is Part 1's own, already-classified churn); exactly 6 methods in the
     itertools home and 4 in the string-iterators home refuse — the
     `next(self._x)` family (`_Product2`/`_Cycle`/`_TakeWhile`/`_DropWhile`/
     `_Take`/`_Drop` `__next__`; the string home's measured set).
   - The first cut's 3 prototype regressions (`format.mojo:432`,
     `logger.mojo:406`, `test_list:647` — invalid
     `(..., int64_t, ..., int64_t)` prototypes) needed a fix under BOTH
     cuts: the prototype block mirrors the pre-pass's BARE entry for
     methods whose body never writes the per-overload `func_param_types`
     entry (now: the fallback's prototype-only entries; before: the
     skipped ones). Fixed in `_emit_struct_method_prototypes`: a `...`
     followed by typed params normalizes to `MojoList *`, and the `*args`
     star-param else branch uses the same sentinel. After the fix: all 5
     affected files gate rc=0 (re-verified under the final code).
   - **False-green guard + the same fallback** (the R2 census class, the
     live false green this session resolved): clean master's
     `std/iter/__init__.mojo` C carried 4 calls to a mangled
     `next_12_IteratorType_5_Int64` with 1 extern declaration and 0
     definitions anywhere — "imported generic, never elaborated, calls
     nothing that defines", invisible to the `-fsyntax-only` gate.
     Mechanism: `next(self._inner)` in a still-generic body erases the
     `Self.InnerIteratorType` field to `int64_t`, and inference then binds
     the callee's `Iterator`-bounded type parameter to that SCALAR
     (`next[IteratorType := Int64]`) — a monomorphization nothing that
     compiles can define. The guard (emit_resolve's
     `_elaborate_generic_call`, inferred branch) refuses exactly this shape
     — the method then lands prototype-only through the same transactional
     fallback as the homes. TWO conditions, both load-bearing (the second
     added after a measured false positive):
       * the argument is a `self`-field whose annotation (the
         `_field_annotations` map) names an unbound type parameter of the
         enclosing struct (scoped by `gen._current_struct_type_params`,
         set/restore around the method emission — free functions,
         closures, and the instantiating TU elaborate exactly as before);
       * AND the callee's own template treats that type parameter as a
         CONTAINER — a `<param>.Element` / `.IteratorType` /
         `.IteratorOwnedType` type-member access in its signature or body
         (`next[IteratorType: Iterator] -> IteratorType.Element` matches).
         The erased-field condition ALONE was wrong: it broke
         `StridedRange._unsigned_count`, whose `ceildiv(self.end -
         self.start, self.step)` arguments are the same erased
         `Scalar[Self.dtype]` fields, but `ceildiv[T: CeilDivable]
         (numerator: T, denominator: T) -> T` has no type-member access —
         `ceildiv[Int64]` is a REAL scalar monomorphization, defined by
         other TUs (measured: bench_heap_parallel / test_math /
         _swisstable all define `ceildiv_1_T_5_Int64`), and the Part 1 tree
         emitted exactly this body and linked it. After the discriminator:
         range.mojo's C is byte-identical to the Part 1 tree, and all 4
         std/iter false-green calls are gone from the generated C (the 4
         methods — `_Enumerate.__next__`, `_MapIterator.__next__`,
         `_PeekableIterator.__next__`, `_PeekableIterator.peek` — are
         prototype-only with diagnostic comments; the removed-definition
         A/B check reports 0 undefined-and-referenced symbols).
   - Warn-set: the first cut's deviation (13/244 — the skipped simd/
     interval bodies no longer triggered their elaboration attempts) is
     SUPERSEDED: under the fallback those lowerable bodies emit again, and
     the final warn-set is **byte-identical to the baseline 15 files / 248**
     (files AND counts, re-measured on the final code).

2. **The zero-arg / direct-struct-return factory subpath** (lifts
   `test/itertools/test_count.mojo` with ladder evidence):
   `def count(start: Int = 0, step: Int = 1) -> _CountIterator:` returns a
   CONCRETE struct that IS the value. The old seed gate's `len(args) < 1`
   early-return seeded nothing, `it` stayed `int64_t`, and `next(it)`
   (measured, in `test_count`) refused. Every piece of the subpath is
   measured, not guessed:
   - `iter_factory.parse_return` gained the bare-struct-name arm —
     `{'wrapper': name, 'kind': 'direct'}`. Seeded ONLY for calls with no
     POSITIONAL args — which includes the measured kwarg form (test_nth's
     `count(start=10, step=2)`); on the positional-arg path
     `_factory_return_for`'s owned/borrowed pick can never select it
     (verified), so a positional `def f(x) -> Concrete` is handled exactly
     as before.
   - `elab_intu._seed_direct_factory` gates it narrow: exactly ONE
     'direct' overload of the name; the wrapper declared `struct <name>(`
     in the home module (a `[` is out of scope — the instantiating-TU path
     handles generics); the wrapper's FIELD order equals the factory's
     PARAMETER order (count: start,step == start,step) — precisely what
     makes the call's positional args map 1:1 onto the synthesized
     fieldwise `__init__`; the factory's own parameter DEFAULTS captured in
     the record as parsed literal nodes (count: 0, 1) — a copy of what the
     factory body `return {start, step}` constructs, not a guess.
   - `_materialize` concrete-struct branch: a bracket-less template gives
     `bind_type_args` nothing to bind (its documented None) and
     `monomorphize_source`'s head match REQUIRES the bracket block (measured
     ValueError: "no generic `fn`/`struct name[...]` found") — so the
     template IS the concrete source and the mangled name is the plain name
     (`mangle`'s zero-arg contract: returned unchanged). Gated on
     `kind == 'struct'` so a hypothetical concrete-fn root keeps its
     pre-subpath honest refusal.
   - **Measured registry gap found on the way**: `_register_named`'s `[\[:]`
     regex matches generic (`[`) and bare (`:`) heads but not concrete-
     with-bases (`(`) — exactly `struct _CountIterator(Iterable, ...)`. Its
     documented scope is generic templates, so it is left untouched; the
     direct subpath performs the same registry write itself (guarded on
     `struct_field_types`, mirroring `_register_named`'s own guard).
   - The emit side (`emit_calls._lower_factory_call`, kind 'direct')
     constructs the wrapper from the factory's own parameters in order —
     call positionals, then kwargs, then the factory defaults — so
     `count()` and `count(start=10, step=20)` are distinct
     `factory_call_key` entries carrying exactly the values the factory
     body would build. `next(it)` then dispatches on the in-TU
     `_CountIterator.__next__` through the existing struct-protocol branch.
   - Ladder: **2/2 PASS** (fresh process, real `gcc -c` + `nm` + link +
     run): checked values 0,1 and 10,30; module-own `T _CountIterator___
     next__` + both `__iter__` overloads in the module's own object; link
     rc=0; the only non-runtime undefined is the documented `assert_equal`
     stub. The spliced `__next__` body is stdlib's real arithmetic
     (`result = self.start; self.start += self.step; return result`).
     Re-ran 2/2 PASS on the final (fallback) code; its C is byte-identical
     to the ladder-verified one.
   - A/B corollary (measured against the Part 1 tree, baffbcb4): the same
     subpath lifts `test/iter/test_nth.mojo`'s kwarg-form call —
     `count(start=10, step=2).nth(5)` becomes in-TU `_CountIterator`
     construction + the (inherited-trait, weak-stub) `_CountIterator_nth`
     — where the Part 1 tree called `std_itertools___init___count_2dbb98`
     as a bare extern with 0 definitions anywhere (its home C was never
     generated — the `next()` refusal of this same family), a link hazard
     the `-fsyntax-only` gate could not see.

### Where the population stands now (measured sweep, 2026-10-21, final code)

Sweep **599 PASSED / 11 FAILED — 11 expected, 0 unexpected, EXIT 0, no
stale entries** (campaign baseline: 592/18; after lift-4: 596/14). Warn set
is BYTE-IDENTICAL to the baseline 15 files / 248 (files AND counts,
re-measured on the final code — the first cut's 13/244 deviation is
superseded by the fallback, above). The 11 declared-red entries
each now carry a per-file measured reason (emitting function, measured
receiver type, the shape the current machinery cannot lower); the shared
`_NEXT_ON_STRUCT` constant was removed with its last user. By root-cause
shape:

| shape | files (emitting function, measured receiver) |
|---|---|
| method-call dependent return (`s.bytes()` on a local `StringSlice`) | `test_iterators` (`test_bytes_iter_empty`, `int64_t`) |
| factory container is a SET LITERAL (`enumerate({4, 5, 6})`) | `test_set` (`test_iter`, `MojoList *`) |
| variadic multi-iterable factory + `out res` parameter | `test_chain` (`test_chain_ref`, `int64_t`), `test_zip` (`test_zip2`, `void *`) |
| two-container dependent return (`_Product2[iterA, iterB]`) | `test_product` (`test_product2`, `int64_t`) |
| thin-FUNCTION type argument (a function value: `map[add_one]`, `take_while[less_than_5]`, `drop_while[pred]`) | `test_map` (`test_map`), `test_take_while` (`test_take_while_basic`), `test_drop_while` (`test_drop_while_basic`) — all `int64_t` |
| `for` over an imported struct (`PythonObject.__iter__ -> _PyIter`; the protocol cursor binds to `MojoList *`) | `test_python_object` (`test_iter`) |
| user-defined `IterableOwned` locals (R2 sibling, local-generic-elaboration gap) | `test_cycle` (`test_cycle_owned`; 15/17 sites work with real values) |
| cross-stdlib `stat` + the out-param result model (R2 doc) | `test_getsize` (gcc -c: implicit declaration of `stat`) |

### Full-tree A/B vs de890235 (fresh-process, 610 files, final code)

State transition: **592 C / 18 ERROR -> 599 C / 11 ERROR** — E->C **7**
(the 2 homes + `test_count` lifted this session, plus lift-4's 4:
`test_enumerate`/`test_peek`/`test_drop`/`test_take`); **C->E 0**; C->C
changed **113** — byte-identical as a SET to the Part 1 A/B's churn set
(113 files), of which 111 are byte-identical to the Part 1 tree's after-
state; only 2 differ, both improvements: `std/iter/__init__.mojo` (the 4
false-green bodies are prototype-only — the only Part 2 C content change
beyond Part 1) and `test/iter/test_nth.mojo` (the undefined
`count_2dbb98` extern is now in-TU `_CountIterator`, above); C->C same
**479**; ERROR-both **11** — the declared red, differing only in the new
`in function \`<name>\`` diagnostic (getsize's failure is identical). The
removed-definition cross-reference on the 113 changed files reports **0
undefined-and-referenced symbols** — the 3 definitions that ARE removed
(`_MapIterator.__next__`, `_Enumerate.__next__`,
`_PeekableIterator.__next__` — the false-green bodies; the 4th,
`_PeekableIterator.peek`, returns a pointer and is outside the checker's
def-regex, but its only references are same-file static dispatch arms) are
unreferenced. The first cut's 152-file C->C set (107 of it churn) and its
133 Class-A link hazards (the `Span_*` family) are both artifacts of the
unconditional skip and are gone under the fallback.

### Acceptance (unchanged, still unmet)

The census must reach 0 sites and the declared `EXPECTED_FAILURES` must
empty. The measured remainder is the 11 above; none of them is a stub or a
silent green — every one fails a real `gcc -c`/codegen with a named, per-
file reason, which is the state this dict exists to declare.

## 2026-10-21 (further): the thin-FUNCTION type argument lifts
(take_while/drop_while); the set-literal container lifts; the map mechanism
lifts; declared-red 9, of which 1 is floor-green

### The thin-function subpath (lifts `test_take_while` and `test_drop_while`,
14/14 ladder each; the mechanism is what test_map needed)

The Part 2 blocker for the three thin-FUNCTION files was that the wrapper's
function type parameter (`_TakeWhileIterator`'s
`predicate: def(InnerIteratorType.Element) thin -> Bool`) had no value
representation, so the instantiation could not be formed and `it` erased to
`int64_t`. It now can, with every piece measured:

1. **`iter_factory.parse_return`'s kwarg arm** reads the dependent return
   `Wrapper[kw=expr, ...]`: `kind` comes from which iterator member the inner
   kwarg names (`IteratorOwnedType` -> owned, `IteratorType` -> borrowed), the
   rest are the FUNCTION parameters (take_while/drop_while's `predicate`).
   A **positional arm** (same session) reads `Wrapper[<bare-ident>]` with
   `kind=None` — map's shape, below.
2. **`elab_intu._seed_one_factory`'s parameter classification**
   (`_wrapper_param_roles`) classifies the wrapper HEADER's parameters by
   annotation: `Iterator`-prefixed -> the inner (bound from the container
   argument), `def(...)` -> the function value (bound from the call's EXPLICIT
   TYPE ARG — `take_while[less_than_5](nums)` passes the function as a type
   argument; nested non-capturing defs bind to their lifted C name
   (`closure_lifted_name`), capturing closures are refused, module-level bare
   names resolve via `_func_csym`), other -> DERIVED (bound from the function
   value's OWN `-> T` return annotation — map's `OutputType`, below). The
   positional arm additionally GATES the bare identifier to an actual def in
   scope (`_find_fn_def`), so a bare type arg (`Foo[T]`) can never bind the
   function slot — the other single-bare-identifier returns in the measured
   stdlib (`_RepeatIterator[ElementType]`, `_Empty[T]`, `_Once[T]`) match the
   arm but are refused downstream (no container argument / no fn arg),
   leaving their call sites exactly as the pre-arm refusal did.
3. **`_factory_return_for`'s kind-None fallback**: map's two overloads
   annotate IDENTICALLY (`_MapIterator[function]` — a positional cannot
   express a pass mode), so the first kind-None overload answers; the pass
   mode is the call argument's `moved`, which the record already carries.
4. **`map` joins `_BUILTIN_FACTORY_HOME`** (test_map calls `map[add_one](l)`
   with NO import line — a compiler builtin whose measured dependent-return
   implementation is std/iter's overloads, exactly like enumerate/iter).
5. **`monomorphize._check_no_value_shadow` member-access exclusion**: the
   shadow check's `var <T>` regex false-positived on map's function
   parameter's OWNED convention `def(var InnerIteratorType.Element) thin ->
   OutputType` (a type position inside a def annotation — take_while's
   `def(InnerIteratorType.Element)` has no `var`, which is why it never
   tripped). The match now requires the name NOT be followed by `.`; a real
   statement-level `var T` / `for T` is followed by `=`, `in`, or EOL.
6. The spliced `Self.predicate(elem)` / `Self.function(next(self._inner))`
   body monomorphizes through the existing `Self.<param>` unit pass to a
   direct call of the lifted function — no new emit-side machinery.

Ladder (fresh process, real `gcc -c` + link + run, value-checking asserts):
**test_take_while 14/14 PASS** (module-level AND nested predicates;
`next()`/`.__next__()`/for-loop/exhaustion forms) and **test_drop_while
14/14 PASS** (incl. the nested `is_zero` predicate). Re-verified 14/14 on the
final code after every subsequent edit in this session.

### The set-literal container (lifts `test_set` OUT OF THE SWEEP; the
full-file ladder stays red on five measured independent gaps)

`test_iter`'s measured blocker was `enumerate(my_set)` over the set LITERAL
`{4, 5, 6}` — `resolve_container` refused a set literal (it accepted
statically resolvable local List / range / nested factory only), so no
record seeded, `it` kept its container-derived type, and `next(it)` (measured
receiver `MojoList *`) hit the hard refusal. Now:

- **`resolve_container` gained the Set arm** (list literal / local / rvalue /
  owned forms, x5 sites) and the seed builds the set-kind record from the
  LIST source; the emit side (`_lower_factory_call`, kind 'set') converts the
  `MojoSet *` through `mojo_set_to_list` — the runtime set's own insertion-
  order walk (the same order the runtime set for-loop iterator uses) — and the
  inner rides the ladder-verified List path end to end.
- **`Set[T](x, y, ...)` constructor arg-append**: the constructor used to
  EVALUATE its args and drop them — a silent empty set (measured: the
  baseline `test_any_all` C is `mojo_set_new()` with zero adds for
  `Set[String]("bleep", "bloop")`, i.e. `any(...)` computed over an EMPTY set
  where the source asserts true). It now appends via `mojo_set_add_int/str/
  bytes`; bare `Set(<MojoSet *>)` copies via `mojo_set_copy`. Both are
  genuine improvements that also land in two GREEN files' C (test_any_all,
  below).
- **Signed-literal `list_literal_elem`**: a list literal with a NEGATIVE
  element failed element inference (the `-` was not parsed), which silently
  kept `test_dict`'s `for i, key in enumerate(keys)` on the old fallback path
  (`keys` is a literal of large/negative int64s); the signed arm seeds it —
  in-TU `_Enumerate` materialization (below).
- **`factory_call_key` folds the explicit type arg** — `take_while[
  less_than_5]` / `take_while[always_true]` over the same local are distinct
  records.

Measured surface: the full file's C gen COMPLETES (11,086 lines, 35 tests;
baseline: `next(...)` hard refusal in `test_iter`, whole-module crash) — the
file leaves the sweep (599->602 PASSED) and `EXPECTED_FAILURES`. The full-
FILE ladder, however, does not link (exactly `check_write_to` + `conforms_to`
undefined, measured in the link step) and its 20-31 test scratch runs
11 PASS / 9 FAIL with five INDEPENDENT measured gap families, none of them
of this doc's `next(<struct>)` class:

- **(A)** `check_write_to` — cross-MODULE test_utils import + `Some[Writable]`
  trait-protocol dispatch; the single-module ladder link cannot supply
  test_utils (link fails on it, as on (C)).
- **(B)** `write_repr_to` / `write_to` — protocol methods lower to the
  constant 0 (in-TU weak stub).
- **(C)** `conforms_to` — the comptime builtin is emitted DECLARATION-ONLY
  (no definition; undefined at link). Landing it needs static trait
  resolution of Set's conditional conformances — a feature.
- **(D)** the Set element methods `_lower_set_method` does not handle:
  `.remove` / `.pop` (no-op, and no raise on missing/empty — measured:
  `.pop()` returns pointer-garbage 0x100000000 on an empty set), `.insert` /
  `.deinit_with` / `.clear_with` (closure-argument methods, no-op), iterator
  `.bounds()` (no-op -> 0) — while `.add` / `.discard` / `.copy` / `.clear` /
  `.update` DO lower (ladder-verified).
- **(E)** the empty `{}` literal convention is an empty DICT
  (`mojo_dict_new`): module-side `set == {}` takes the erased path (`_
  eq_operand_kind`'s ctype check hits `MojoDict *` before the SetExpr node
  check) -> `mojo_value_eq(set, dict)` -> 0 (kills test_discard / test_clear);
  `set > {}` / `set < {}` hits the container-ordering REFUSAL, which raises a
  CPython-style `TypeError` the codegen's unhandled-exception path then
  `exit(1)`s on — killing the whole ladder run (test_greaterthan /
  test_lessthan are excluded from continue-mode maps for this reason).
- **(F)** cross-module `hash(<set>)` is not content-derived (measured: two
  sets with equal content hash to different words).

The reduced-file scratch (11 tests: construction/move/copy/len/in/equal/
bool/iter/add/comprehension/iter_owned) is **LADDER PASS 11/11** with real
values, including `test_iter`'s full `next()` / tuple-subscript / `it.
__next__()`-exhaustion flow — the enumerate(set) path proven end to end.
Stale-binary lesson recorded in the session notes: an earlier continue-mode
run showed test_discard PASS from a stale binary; remeasured with a fresh
build (both whole-run and per-test argv) it reproduces the (E) failure with
byte-identical generated C across trees.

### The map mechanism (the file stays red on ONE cross-module test)

`test_map`'s Part 2 blocker was the same thin-function gap, in its positional
form: `_MapIterator[function]`, `function: def(var InnerIteratorType.Element)
thin -> OutputType`, with `OutputType` a SEPARATE derived parameter. With the
subpath above (items 1-6, positional arm + derived binding from the function
value's own return annotation: `def add_one(x: Int) -> Int` supplies
`OutputType=Int`, `def to_str` supplies `String`), the reduced-file scratch
(2 tests, the CopyCounter test removed) is **LADDER PASS 2/2** with real
values: `next(m) = 2, 3, 4` (Int output), `next(m2) = "1", "2", "3"` (String
output through the in-TU `_ListIterOwned` + `mojo_list_get_int` chain,
verified by disassembly), exhaustion raising StopIteration via `m.__next__()`
in both; `map[double](l^)` exercises the owned overload (2, 4, 6). The ONE
remaining test, `test_map_function_can_take_owned_value`, is blocked by an
INDEPENDENT cross-module gap: `CopyCounter` from test_utils (`CopyCounter[
NoneType](None)` + `.copy_count`) — the single-module link cannot supply
test_utils (the (A) family); its container argument (`var list = [CopyCounter
[NoneType](None)]`) is also refused by the seed's container gate (measured
note: `map(...): container argument is not a statically resolvable local List
/ range / nested factory`). A/B state: **E->E with the crash relocated** —
baseline: `next(...) (receiver typed int64_t) in function test_map`; final:
`... in function test_map_function_can_take_owned_value`. The mechanism
works; the file's remaining red is the test_utils struct, not map.

Driver note (this session, both ladders): the char* pointer heuristic's floor
was 1<<40, which MISSES this machine's 33-bit malloc heap (0x1_0...) —
test_map's `assert_equal(next(m2), "1")` (a char* pair there) fell into the
word comparison and failed on pointer identity. The floor is now 1<<32 (the
equal-values case still passes — the strcmp branch compares a pointer with
itself); the tested asserts carry no unequal >=1<<32 integer pair, so the
widened range cannot dereference an integer.

### test_cycle — the 2 remaining sites, remeasured (surface unchanged,
refusal now at the seed)

The 2 user-owned sites (`cycle(_owned3(1, 2, 3))` line 283 in
`test_cycle_owned`, `cycle(_owned1(42))` line 302 in `test_cycle_owned_
single`) are now refused at the SEED's container gate (measured notes, x2:
`cycle(...): container argument is not a statically resolvable local List /
range / nested factory`): the container argument is a LOCAL FUNCTION CALL
whose bracketed return type requires local generic elaboration, and its value
is a USER-DEFINED `IterableOwned` struct (`_CopyableOwned[3]` — module-local,
comptime-parameterized, in-TU `_CopyableOwnedIter[3]` over `Array[Int, 3]`).
The boxed `it` local then hits next()'s hard refusal (receiver typed
`int64_t`, in `test_cycle_owned` — measured, unchanged from clean master).
15/17 sites work with real values. The blocker is the local-generic-
elaboration gap (R2 sibling) + the in-TU user-struct iterator — both
documented, neither stubbed.

### Full-tree A/B vs clean master 5179db5a (fresh-process, 610 files,
final code)

**603 identical**; **E->C 3** — `test_take_while` / `test_drop_while` /
`test_set` (above); **E->E 1** — `test_map` (crash relocated to the
CopyCounter test, above); **C->E 0**; **C->C 3**, every delta classified:

| file | the delta | classification |
|---|---|---|
| `test/builtin/test_bool.mojo` | the `map[gt0](l)` sites in `test_all` / `test_any` materialize the real in-TU `_MapIterator[...Bool...test_all_gt0 / test_any_gt0]` + `_ListIterOwned[Int]` (baseline: the call boxed to `int64_t` — verified in the before-C; NOT an undefined extern, so no site of the sibling doc's class is removed) | call-site improvement; the `all()` / `any()` CONSUMPTION of the wrapper still hits the runtime-dispatch fallback (`mojo_is_registered_dict/set` probe on the wrapper pointer — measured: the `assert_false(all(map[gt0](l2)))` site computes the pointer's truthiness, 4294967297, and fails at runtime — same status as the baseline's int64 garbage; test_bool is floor-green only and is not executed by the bucket). Extending all()/any() to in-TU iterators is recorded as the next narrow feature, deliberately out of this session's scope |
| `test/collections/test_dict.mojo` | `for i, key in enumerate(keys)` (`keys` = a list literal of large/NEGATIVE int64s) seeds the enumerate record through the signed-literal `list_literal_elem` arm -> in-TU `_Enumerate` + `_ListIterOwned` materialization (baseline: the old fallback loop) | improvement |
| `test/builtin/test_any_all.mojo` | the `Set[String]("any")` / `Set[String]("bleep", "bloop")` constructor sites now APPEND their args — 12x `mojo_set_add_str` (baseline: `mojo_set_new()` with zero adds — a silently EMPTY set, semantically wrong against the file's own `assert_true(any(...))`) | improvement (the Set-constructor fix, above) |

The removed-symbol cross-reference on the 3 changed files reports **0**
undefined-and-referenced symbols (the only removed line, test_dict's
`_known[]` static, is a hunk-position artifact — the array is present in the
after-C, grown by the 2 new in-TU type tags).

### Where the population stands now (measured sweep, 2026-10-21 (further),
final code)

Sweep **602 PASSED / 8 FAILED — 8 expected, 0 unexpected, EXIT 0, no stale
entries** (was 599/11 at 5179db5a). Warn set BYTE-IDENTICAL to the baseline
15 files / 248. The 8 declared-red entries each carry a per-file measured
reason; by root-cause shape (updated table):

| shape | files (emitting function, measured receiver) |
|---|---|
| method-call dependent return (`s.bytes()` on a local `StringSlice`) | `test_iterators` (`test_bytes_iter_empty`, `int64_t`) |
| variadic multi-iterable factory + `out res` parameter | `test_chain` (`test_chain_ref`, `int64_t`), `test_zip` (`test_zip2`, `void *`) |
| two-container dependent return (`_Product2[iterA, iterB]`) | `test_product` (`test_product2`, `int64_t`) |
| thin-FUNCTION type argument, positional form — mechanism LIFTED, one cross-module test remains | `test_map` (`test_map_function_can_take_owned_value`, `int64_t` — the CopyCounter container gate refusal; the ladder 2/2 above) |
| `for` over an imported struct (`PythonObject.__iter__ -> _PyIter`; the protocol cursor binds to `MojoList *`) | `test_python_object` (`test_iter`) |
| user-defined `IterableOwned` locals (R2 sibling, local-generic-elaboration gap) | `test_cycle` (`test_cycle_owned`; 15/17 sites work with real values) |
| cross-stdlib `stat` + the out-param result model (R2 doc) | `test_getsize` (gcc -c: implicit declaration of `stat`) |
| (floor-green, ladder-red) set-literal container — 5 independent gaps A-F above | `test_set` (out of the sweep; full-file ladder link fails on `check_write_to` + `conforms_to`) |

### Interpreter verification (mandated 3.14.8; the session's first
measurements ran under PATH 3.15)

The project's interpreter is /opt/local Python 3.14.8, but this session's
first measurements ran through `python3` on PATH (homebrew 3.15). The CAS
key folds in the codegen sources + env + git epoch only — the interpreter
is invisible to it — so a cache is only sound if both interpreters emit
identical C. Measured with the uncached generator on 11 representative
files covering every codegen path this session changed (the three lifted
mechanisms, the three C->C files, three sanity/remaining-red files, and
std/iter itself): the generated C is BYTE-IDENTICAL under 3.15 and
3.14.8 (10/11 hash-equal; test_getsize raises under both, its message
differing only in a per-run random temp-dir name). Everything was then
remeasured under 3.14.8: ladders take_while 14/14, drop_while 14/14,
set-scratch 11/11, map-scratch 2/2; sweep 602/8 (8 expected, 0
unexpected, EXIT 0) with the warn set again byte-identical 15/248; the
5179db5a baseline (fresh worktree) 599/11; bucket **53/53 (rc 0,
ps-verified /opt/local 3.14)** — the invalidated 3.15 bucket run was
discarded. The full-tree A/B above is unaffected: both arms ran under one
interpreter, and the two are proven output-identical.

### Acceptance (unchanged, still unmet)

The census must reach 0 sites and the declared `EXPECTED_FAILURES` must
empty. The measured remainder is the 7 above plus the floor-green `test_set`
(ladder-red on A-F); none of them is a stub or a silent green — every one
fails a real `gcc -c`/codegen/link with a named, per-file reason, which is
the state this dict exists to declare.

## 2026-10-22 (further, part 4): the out-res factory subpath lifts
chain/zip, the pyobj-list arm lifts test_python_object — declared-red
8 -> 5, sweep 602/8 -> 605/5

### The 3 lifts (each with its measured mechanism)

1. `test/iter/test_chain.mojo` and `test/iter/test_zip.mojo` — the part-4
   **variadic + out-parameter factory seed subpath** (the out-res seed):
   `chain`/`zip` are `*iterables: *Ts, out res:
   _ChainedIterator[*inners]` / `_ZipIterator[*inners]` — the subpath binds
   the N container arguments to N inner iterators and threads the dependent
   `out res` return through the wrapper's borrowed overload
   (iter_factory's `variadic_meta` carries the seed-only element knowledge).
   Before: `next(it)` hard refusal, receiver `int64_t` (chain, in
   `test_chain_ref`) / `void *` (zip, in `test_zip2`) — the `out res` never
   constructed. After: both modules compile; the value ladders were re-run
   this session with parity to 2026-10-21 — chain PASS 4/4; zip 11/12
   (`test_zip_bounds` FAIL-REAL, words 0 / 4294967298 — a real runtime value
   assert, not a gate regression).
2. `test/python/test_python_object.mojo` — the part-4 **pyobj-list seed arm**
   (emit_calls): a `PythonObject.__iter__()` call as the loop's container
   argument lowers through the RECEIVER's box, which IS the MojoList *
   pointer (measured: the runtime method dispatch unboxes it the same way);
   the borrowed inner construction then runs on the public representation
   exactly as for a list local. Before: `next(<MojoList *>)` — a raw
   container pointer, hard refusal in `test_iter`.

### The 3 shape-mismatch fixes (this session; the pre-shape-fix part-4
sweep was 602/8 with exactly these 3 unexpected)

1. `std/collections/string/_parsing_numbers/parsing_floats.mojo` and
   `std/benchmark/_progress.mojo` — **Shape-B materialization**
   (emit_resolve `_sce_simple_emit`): a `MojoTuple_*`-typed local or field
   assigned from a list value materializes by FIELD READS through the
   runtime getters (`mojo_list_get_int`/`double`/`str` by field ctype) into
   same-type temps plus plain stores (the -fgimple component-ref rule
   forbids storing a cast result through `.`/`->`). `_progress` additionally
   needed the **real-list default** (calls_shared `_default_expr_to_pair`):
   a `(80, 24)` default for a `MojoTuple_`-annotated param now builds the
   real runtime list (measured: the struct then reads 80/24 through the
   materialization) instead of the zero word the materialization would have
   read from a NULL list.
2. `std/simd.mojo` — the **`Self`-parameter registration** fix: a
   `Self`-annotated param (`def eq(self, rhs: Self)`) erased to the p3
   int64_t word in the `func_param_types` registration while the definition
   emits `SIMD *`; `_emit_call` saw ptype==atype and skipped the cast, and
   gcc flagged the raw word arg against the real `SIMD *` prototype (3
   sites in `__divmod__`: `denominator.eq(0)` / `.lt(0)`). Fixed in all
   THREE registration sites that must agree (funcs_shared `_signature_
   ctypes`, module_gen's earlier struct-method loop, module_gen's LATER
   struct-method loop — the last ran last and was the stale overwriter;
   its value feeds `_struct_method_csym`'s bare->qualified setdefault
   mirror, which every pre-definition call site reads through `_emit_
   call`). Measured gcc-mp-15 -fgimple quirk: a word arg to a struct-
   pointer param is diagnosed ONLY in a pointer-returning function — p3's
   int64-returning divmod hid the identical shape, so the explicit
   `(SIMD *)` cast is p3's value made explicit, not a behaviour change.
   An interim aggressive word->pointer upgrade in `_emit_call` was
   REVERTED: it caused 2 regressions (`std/collections/string/string.mojo`
   and `std/python/_cpython.mojo`, "makes integer from pointer" —
   `mangled_sig` is not always the correct answer when the definition's
   real param type is a word); the registration-side fix is the root fix,
   and both regression files re-verify 0-error on fresh uncached
   generation.

### Where the population stands now (measured, final code, 2026-10-22)

Sweep **605 PASSED / 5 FAILED — 5 expected, 0 unexpected, 0 stale** (was
602/8 at the part-3 close with all 8 expected; the pre-shape-fix part-4
sweep was 602/8 + 3 stale = the 3 lifts above). Warn set: 19 files / 294
warnings — BYTE-IDENTICAL between the pre-fix part-4 sweep and this
sweep (the session's fixes are warning-neutral); it moved from the
part-3 baseline 15/248 with the part-4 changeset itself (before this
session): +4 files (std/utils/coord 1, test/ffi/test_unsafe_union 15,
test/utils/test_coord 7, test/utils/test_variant 19) and
test/builtin/test_device_passable 7 -> 11. A/B fresh-process 610 vs the
part-3 baseline: 605 C / 5 E, C->E 0, E->C 3 (the lifts above), C->C 123
(the whole part-4 changeset), removed-symbol hazard 0; vs the pre-fix
part-4 snapshot: C->C 39, of which 5 are byte-identical to the true
pre-fix C (that snapshot's own stale cache entries for the 5 typedef
files) and the other 34 are the Self-registration overload-suffix /
extern-prototype / call-cast churn plus the materialization — no new
function classes. no-new-casts 17 -> 19 (2 deliberate measured unboxes,
ledger entries in `test_no_new_container_casts.py`).

The 5 declared-red entries (the part-3 table minus the 3 lifts; the
product row remeasured this session — the refusal relocated):

| shape | files (emitting function, measured receiver) |
|---|---|
| method-call dependent return (`s.bytes()` on a local `StringSlice`) | `test_iterators` (`test_bytes_iter_empty`, `int64_t`) |
| thin-FUNCTION type argument — one cross-module test remains | `test_map` (`test_map_function_can_take_owned_value`, `int64_t` — the CopyCounter container gate refusal; the scratch ladder 2/2 stands) |
| local-fn-call container returning a user-defined `IterableOwned` (R2 sibling) | `test_cycle` (`test_cycle_owned`; 15/17 sites work with real values) |
| two-container product — the OWNED local-fn-call arguments (R2 sibling) | `test_product` (`test_product2_owned`, `int64_t` — the non-owned `test_product2`/`_param`/`_unequal`/`_copies` now lower) |
| cross-stdlib `stat` + the out-param result model (R2 doc) | `test_getsize` (gcc -c: implicit declaration of `stat`) |

### Acceptance (unchanged, still unmet)

The census must reach 0 sites and the declared `EXPECTED_FAILURES` must
empty. The measured remainder is the 5 above plus the floor-green
`test_set` (ladder-red on A-F); none of them is a stub or a silent green
— every one fails a real `gcc -c`/codegen/link with a named, per-file
reason, which is the state this dict exists to declare.
