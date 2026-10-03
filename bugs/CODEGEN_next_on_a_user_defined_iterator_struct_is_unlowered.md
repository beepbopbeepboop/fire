# `next(<user-defined iterator struct>)` has no lowering, and the callee's
# type is not inferred either

## Status

OPEN, and smaller: **19 files, down from 22.** Three genuinely went green —
`test/iter/test_empty.mojo`, `test/iter/test_once.mojo`,
`test/itertools/test_repeat.mojo` — and are out of `EXPECTED_FAILURES` with
per-file artifact evidence (below). `undef_import_census` is **96 / 51 / 60,
UNCHANGED**, and that is the honest reading rather than a null result: the
census only counts files that COMPILE, and these three did not before, so
there was never a census row to remove. The census will not move until the
remaining 19 do.

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
| `test_module_cache.py` | 131 / 0 | 131 / 0 |
| `test_gimple.py` | 354 / 0 | 354 / 0 |
| `test_link_mode.py` | 11 / 0 | 11 / 0 |

**What is still open, in the order the next session should take it.**

1. **Bounded associated-type resolution**, for the remaining `std/iter`
   family: `peekable(list) -> _PeekableIterator[type_of(iterable)
   .IteratorOwnedType]`, with `List.IteratorOwnedType = _ListIterOwned[Self.T]`
   (std/collections/list.mojo:361) → `_ListIterOwned[Int64]`. Read the
   struct's own `comptime Name[...] : Trait = <expr>` from its defining
   module. Do NOT textually substitute `Self.<comptime member>` — commit
   ae8f0493 substitutes `Self.<TYPE PARAM>` only, and that scoping is right.
   `_refine_generic_return_type` (mojo/middle/resolve_shared.py:1453) is the
   hook: it re-resolves a return annotation with the struct-aware
   `gen._resolve_type` after substituting mangled type args, but it does NOT
   receive the call's argument types, which this needs.
2. **Overload selection on a trait bound**, for `peekable`'s two
   `Some[Iterable]` vs `Some[IterableOwned]` overloads.
3. **Overload dispatch outside the iteration protocol** — the 11-file table
   above. Each row is `error: passing argument N of '<Struct>_..._m_hash'`,
   i.e. a call site still holding the erased view beside a definition with the
   real one. That is the same one-way information loss as `FormatStruct`'s two
   `fields`, and it wants the call site's real argument inference, not another
   naming change.

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
