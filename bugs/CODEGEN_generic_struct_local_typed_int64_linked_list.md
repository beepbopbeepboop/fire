# A local bound to a generic struct instance is typed `int64_t`, so `test/collections/test_linked_list.mojo` fails gcc

## Status (2026-10-30): OPEN. Found while landing `work/fix-red-fix-leftover-bug-codegen-dict-literal-container-key-`; NOT caused by that branch.

The `stdlib-syntax` job's only unexpected failure in `test/collections` is
`test/collections/test_linked_list.mojo`. Its generated C does not compile.

### Evidence

- `python3 compile_stdlib.py --roots test/collections -j1` on **pure master**
  (`git archive master`): `PASSED: 58 / FAILED: 1 (0 expected, 1 unexpected)`,
  the failure being `test_linked_list.mojo`.
- The same sweep on the **merge of master and the leftover-fix branch**
  (`git merge-tree --write-tree master HEAD`): identical result.
- The generated C for `test_linked_list.mojo` is **byte-identical** between
  master and the merge (`diff` empty), so the branch's change
  (`_literal_needs_kinds` tuple row, `emit_exprs.py`) does not reach this file.
- gcc (`gcc-mp-15 -fgimple -fsyntax-only -D__MOJO_STDLIB_MODE__`, with the
  tree's own `runtime/` include) reports two errors, both in
  `test_linked_list_test_iter`:
  - `test_linked_list.mojo:657`: `assignment to 'int64_t' from 'MojoList *'`
    (`check_write_to(...)`).
  - `test_linked_list.mojo:631`: `mojo_list_get_int` passed an `int64_t`
    where a `MojoList *` is expected (`_ = it.__next__()`).

### Root cause (what is wrong in the generated C)

In `test_linked_list_test_iter` the locals are declared as scalars:

    int64_t l;
    int64_t it;
    int64_t riter;

`l` is `var l = LinkedList[Int](1, 2, 3)` and `it` is `l.__iter__()`. A
`LinkedList` / `_LinkedListIter` value is a struct, so it must be a pointer
or struct type. The generic-struct elaboration of `LinkedList[Int]` now
succeeds on master (commit that made `elaborate._struct_layout_anns` accept
`AssignStmt` fields), so the constructor call is lowered, but the local's
type is still resolved to the scalar default. Every use of `it`/`riter` then
goes through the scalar `mojo_list_get_int` / `int64_t` path.

Minimal repro (master tree, `compile_module_to_c_cached` on this program):

    from collections import LinkedList
    def main():
        var l = LinkedList[Int](1, 2, 3)
        var it = l.__iter__()
        print(it.__next__())

emits `int64_t l;` and `int64_t it;` (see the C near `int64_t l;` in the
generated `main`).

### Why it was previously hidden

Before master's `elaborate.py` fix, `LinkedList[Int]` failed to elaborate
(`AttributeError: 'AssignStmt' object has no attribute 'name'`, recorded in
`_generic_struct_elaboration_failures`). Those modules then fall back to
source and the file compiled. Once elaboration succeeds, the local-typing gap
is reached and gcc sees it. So the gap predates the fix; the fix exposed it.

### Exact next step

1. Find where a `VarDecl`/`AssignStmt` whose RHS is a generic-struct
   constructor call (`Struct[Args](...)`) gets its declared type. Likely
   candidates: `emit_resolve._elaborate_generic_struct_call` (returns the
   constructed name only for the call itself) and the local-type inference
   in `gimple_codegen` / `mojo/backend_gimple` that falls back to `int64_t`
   when the call is not a known struct name at inference time.
2. Make the local take the elaborated struct's name (`LinkedList_int64_t *`
   or the typedef the registration produced), and make `l.__iter__()` return
   the iterator struct, not a scalar.
3. Narrow check: compile the minimal repro above and gcc-check the generated C;
   then `compile_stdlib.py --roots test/collections` must report
   `FAILED: 0`. The gate's `stdlib-syntax` job is the integrator's to run.

Area: codegen, generic-struct locals. Not in the dict-literal claim.

## Status (2026-10-31): PLANNING ROUND. The gcc symptom no longer reproduces on current master; the defect (a stubbed, wrong program) is unchanged. Guide below.

### Measurement (this tree, `033011d79`)

- `compile_module_to_c(src, test_linked_list.mojo, 'test_collections_test_linked_list', linkable=False)`
  then `gcc-mp-15 -fgimple -Iruntime -fsyntax-only -D__MOJO_STDLIB_MODE__`:
  **0 errors, rc 0**. The two errors quoted above are gone (later commits changed
  the stub/variadic-extern shapes), so `stdlib-syntax` no longer flags the file.
- The generated program is still WRONG, only compile-clean. `test_iter` emits
  `int64_t l; l = (int64_t)0; /* indirect call via SubscriptExpr */`,
  `/* int64_t.__iter__() stubbed */`, `/* int64_t.__next__() stubbed */`.
  Every `LinkedList[X](...)` in the file is a literal 0; the test could only
  "pass" by never running.
- Why (instrumented `emit_resolve._register_generic_struct`): elaboration of
  `LinkedList[Int]` succeeds (`_generic_struct_elaboration_failures` empty),
  but registration returns None for all 82 sites. The elaborated template has
  duplicated method names `__init__ pop maybe_pop __iter__` and
  `_register_generic_struct` declines any struct with a duplicated method
  (`_seen_names` rule) because the `.o` route cannot name an overload's hashed
  C symbol from the erased parameter types. `MoveCounter` declines the same way.
  So the doc's earlier "elaboration now succeeds, local typing is the gap" was
  half right: the gap is the registration refusal, not local typing.
- `elab_intu._protocol_only_overloads` is the in-TU route's gate: it accepts a
  struct only if its duplicated names are all in `{__iter__, __next__,
  __has_next__}`. LinkedList is outside it, and `seed()`'s fallback
  `_d2_ctor_args` only answers kwarg-bracket and bare-literal spellings, so
  `LinkedList[Int](1, 2, 3)` is never enqueued.

### Walls, in the order they were hit (each measured by monkeypatching in `.tmp/`, nothing landed)

1. **Seed.** Making `_d2_ctor_args` fall back to `_concrete_args(work,
   'struct', base, node)` for a positional concrete bracket enqueues
   `('struct','LinkedList',('Int',))`. `_rewrite_callees` already finds it
   (it tries `_concrete_args` first). With this alone `l` becomes
   `LinkedList_11_ElementType_3_Int *` and the ctor is
   `..___init___bacc2c(_t1, list, 0)` (the hashed overload resolves),
   but see 2-4.
2. **Comptime alias `_NodePointer = Optional[Pointer[Node[Self.ElementType],
   MutUntrackedOrigin]]`**: `_eval_comptime_type_aliases` looks `Optional`'s
   template up in LinkedList's own source and refuses ("does not bind
   positionally"). Fix: fall back to `_module_src(gen, abase, 'struct')` then
   `_container_home(gen, abase)[1]` (prelude names have no import line). Tried;
   it advances to wall 3.
3. **`Optional[Pointer[Node[Int], ...]]` is then enqueued for in-TU
   materialization** and refused ("no source for 'Optional'": it is not in
   `_imported_generic_structs`; needs `_register_named(gen, <optional.mojo>,
   ['Optional'])`). Optional is also the documented regression source in
   `_protocol_only_overloads`' table (`dup = ['__eq__','__init__','__iter__']`;
   test_optional's empty-subscript arity). The decision needed: model an alias
   whose base is `Optional`/`Pointer` as the erased tagged word the rest of
   the codegen already uses (`_head`/`_tail` field type `int64_t`/box), NOT as
   a materialized struct. Reading A: skip nested enqueue for bases in
   `{Optional, Pointer, UnsafePointer}` and substitute the erased spelling in
   the alias text. Reading B: materialize Optional (rejected by the table).
   Prefer A.
4. **Iterator return types are erased.** The elaborator's `info['methods']`
   gives `__iter__ -> int64_t`; even a registered LinkedList leaves `it`
   scalar. In-TU materialization fixes this only if `_LinkedListIter[T,
   origin]` is also materialized (it is a nested `IteratorType`
   comptime alias with a `[//, iterable_origin]` parameter, which
   `_eval_comptime_type_aliases`' regex (`comptime _x = Base[`) does not
   match: `comptime IteratorType[...]: Iterator = ...`).

### Implementation plan (execute in this order)

1. `elab_intu._d2_ctor_args`: add a branch for a POSITIONAL bracket
   (`not _d2_kwarg_bracket`) returning `_concrete_args(...)` ONLY when the
   struct is not `_protocol_only_overloads` (i.e. the `.o` route declines it;
   confirm with the same predicate `_register_generic_struct` uses, factor
   that predicate into one helper used by both so they cannot drift).
2. `_eval_comptime_type_aliases`: the base-home fallback (3 lines, above) and
   a `_ERASED_ALIAS_BASES = {'Optional','Pointer','UnsafePointer'}` rule that
   substitutes the field's existing erased spelling instead of enqueueing.
3. Extend the alias regex to `comptime\s+(_?[A-Za-z]\w*)(\[[^\]]*\])?\s*(?::[^=]+)?=\s*Base\[`
   so `IteratorType[...]` is seen; enqueue `_LinkedListIter`.
4. Re-measure on `test_linked_list.mojo`: no `/* stubbed */`, no `indirect call
   via SubscriptExpr`, `int64_t l;` gone; then the same on `test_optional`,
   `test_arc`, `test_bitset`, `test_static_tuple` (the table's other `dup =
   ['__init__']` members) because step 1 changes how they are called.

### Tests that will prove it

Add to `test_gimple.py` (next to the existing generic-struct cases) a
compile-only test that builds the minimal repro through
`build_stdlib_dylib.compile_module_to_c` (path under the stdlib so
`std.collections` resolves, `from std.collections import LinkedList`) and
asserts the C contains none of `int64_t l;`, `indirect call via
SubscriptExpr`, `__iter__() stubbed`. It FAILS today (all three present) and is
the pin for step 4. Run with `python3 tools/memslot.py --gb 8 --label x --`.
Gate verdicts owed by the integrator: `stdlib-syntax` `U` must not increase;
`stdlib-dylib` skip count must not increase.

NOT started this round: the code (steps 1-3 are one coherent change that must
land together, because step 1 alone enqueues and then refuses, per wall 2/3).

## Status (2026-11-01): PARTIAL FIX LANDED — seed + erased-word alias; the iterator/Node typing remains.

### What landed (`mojo/backend_gimple/elab_intu.py`, test `test_generic_struct_local_linked_list.py`)

- `_duplicated_method_names(gen, base)`: ONE reading of a template's overloaded
  method names, now shared by `_protocol_only_overloads` and the new branch so
  the two cannot drift.
- `_positional_bracket_ctor_args` (reached from `_d2_ctor_args`'s non-kwarg
  bracket case, so the seed and `_rewrite_callees` agree): a POSITIONAL concrete
  bracket ctor call `Struct[Int](...)` of a struct whose duplicated methods are
  OUTSIDE the iteration protocol is enqueued for in-TU materialization. Gated to
  scalar type arguments (`gimple_ctypes._TYPE_MAP`) and excluding
  `_ERASED_WORD_STRUCTS` (`Optional`, `OptionalReg`, `Pointer`, `UnsafePointer`).
  Measured why both gates: unrestricted, `test_linked_list` went 0 -> 8 gcc
  errors (an imported non-struct-registered element such as `CopyCountedStruct`
  erases `get_nth`'s return to `int64_t`) and `test_optional` 0 -> 2
  (`Optional_..___getitem__` arity).
- `_eval_comptime_type_aliases`: an alias whose base is an erased-word struct
  (`_NodePointer = Optional[Pointer[Node[T], o]]`) now substitutes its own
  spelling and enqueues nothing (walls 2 and 3 of the 2026-10-31 guide).
  Replacement of `Self.<alias>` is by whole-word regex.
- Effect on the minimal repro: `l` is `LinkedList_11_ElementType_3_Int *`, the
  hashed `__init__` overload is called, the `indirect call via SubscriptExpr`
  is gone from `main`, and the stub count in the probe dropped 812 -> 59 once
  the alias fix was in. gcc `-fsyntax-only` is clean on the probe,
  `test_linked_list`, `test_optional`, `test_deque`, `test_dict`, `test_set`,
  `test_list`, `test_arc`, `test_bitset`, `test_iter` (0 errors; stub counts
  equal to master except `test_linked_list`/`test_deque`/`test_bitset` which
  now materialize instead of literal-0).

### What remains (why the doc stays)

1. `it = l.__iter__()` is still `int64_t it;` and `it.__next__()` is stubbed:
   `info['methods']` erases `__iter__ -> int64_t`; `_LinkedListIter` needs
   materializing via `LinkedList.IteratorType[...]`, a parametrized comptime
   alias (`comptime IteratorType[iterable_mut: Bool, //, iterable_origin: ...]:
   Iterator = _LinkedListIter[downcast[Self.ElementType, Copyable],
   iterable_origin]`) that `_COMPTIME_ALIAS_HEAD_RE` does not match, with a
   `downcast[...]` call in the argument and an erased origin parameter.
2. `Node[T]` methods (`next`, `prev`, `single`, `unsafe_with_layout`,
   `_into_value`, ~59 stubs in the probe) are called on the erased
   `Optional[Pointer[Node]]` word: `Node[Int]` is never materialized because
   the pointer alias is erased. Needs `Pointer[Node[T], o]` typed as `Node_T *`
   in the field/return types (a tagged-word `Optional` of a struct pointer).
3. Struct-valued element types (`LinkedList[CopyCountedStruct]`,
   `LinkedList[LinkedList[...]]`) are refused by the scalar gate until the
   element's imported non-generic struct is registered before the materialized
   methods' annotations are resolved.
4. The pin for the whole bug (no `stubbed` in the generated C for the repro) is
   not in the test yet; add it when 1-2 land, then delete this doc.

NOT run: gate / `stdlib-syntax` / `stdlib-dylib` (the integrator's). The
`test_linked_list`/`test_deque`/`test_bitset` outputs change, so `stdlib-syntax`
`U` and `stdlib-dylib` skip count are owed a check.

## Status (2026-11-01, later): PLANNING ROUND — remaining work is one coherent program (iterator + typed Node pointer); guide below.

### Measurement (this tree, probe = the minimal repro, `.tmp/` script over `test_generic_struct_local_linked_list._compile()`)

- `test_generic_struct_local_linked_list.py` passes (`l` is `LinkedList_11_ElementType_3_Int *`,
  hashed `__init__` called). `main` still has `int64_t it;`,
  `_t7 = LinkedList_11_ElementType_3_Int___iter___0120be (l);` (returns `int64_t`) and
  `/* int64_t.__next__() stubbed */`. 59 `stubbed` markers in the whole TU, by receiver method:
  `Node` methods `next prev single unsafe_with_layout unsafe_leak _into_value __hash__` (~50, every one
  on an `int64_t` word), plus `IteratorOwnedType __next__ write_sequence_to _write_self_to FormatStruct
  TypeNames params fields`.
- So the two remaining walls are NOT independent: materializing `_LinkedListIter` alone gives a typed
  `it` whose `__next__` body is itself the `self.curr.value()[].next()` Node-word stub. Landing the
  iterator without the Node model would make `it` a struct but `print(it.__next__())` still wrong.
  This is why no piece landed this round: each half alone leaves the repro's output unchanged.

### Decision needed (readings), then the plan

The root of walls 1-2 is that `Optional[UnsafePointer[Node[T], MutUntrackedOrigin]]` is "an erased
word" (`_ERASED_WORD_STRUCTS`), so `Node[T]` is never named and `.next()` has no receiver type.
Reading A (recommended): model `Optional[UnsafePointer[X, o]]` / `Optional[Pointer[X, o]]` where `X`
is a materialized struct as `X *` with NULL = None. This is the representation the rest of the
struct-pointer codegen already uses (a struct local is `X *`), `not p` / `p.value()` / `p.value()[]`
become NULL test / identity / identity, and no tagged word is needed. Reading B: keep the tagged word
and teach every method call to recover the pointee type from the alias text; rejected, it is the
current failure shape (the type exists only in the spelling).

### Implementation plan

1. `elab_intu._eval_comptime_type_aliases`: for an erased-word base whose innermost argument is a
   `Struct[...]` with scalar args, enqueue that struct (`Node[Int]`) and make the alias name
   `<mangled Node> *` (NOT the spelling) so field/return annotations resolve through the registered-name
   branch to a pointer type. Pointer-nesting is `Optional[UnsafePointer[Node[T], o]]` -> one `*`.
2. Emit side (`emit_exprs`/`emit_methods`): `.value()` on a pointer-typed Optional receiver is the
   identity, `not x` / `if x` is `x == 0` / `x != 0`, `x[]` on `UnsafePointer[Node]` is identity (the
   struct is already `*`), assignment of `None` to such a field is `0`. Find the existing
   `Optional.value` lowering by grepping `unsafe_value` / `_ELEM_COPY_RE` branch (a) in `emit_methods`.
3. Parametrized alias: widen `_COMPTIME_ALIAS_HEAD_RE` to
   `comptime\s+(_?[A-Za-z]\w*)(\[[^\]]*\])?\s*(?::[^=]+)?=\s*Base\[`; for `IteratorType[..., //, o]`
   drop the origin/mut parameters (erased), evaluate `downcast[T, Trait]` to `T`, and rewrite
   `Self.IteratorType[origin_of(self)]` (return annotation text) to the mangled iterator. `_LinkedListIter`
   has defaulted `forward: Bool = True` and a leading `mut: Bool, //` — `type_param_names` must skip the
   infer-only group and `mm.mangle` must fold defaults, otherwise the positional-binding refusal fires.
4. Re-measure: zero `stubbed`, `int64_t it;` gone; `test_optional`, `test_arc`, `test_bitset`,
   `test_deque`, `test_dict`, `test_set`, `test_list` gcc `-fsyntax-only` clean with unchanged stub counts.
5. Struct-valued elements (`LinkedList[CopyCountedStruct]`): register the element's imported struct
   before resolving materialized annotations, then lift the scalar gate in
   `_positional_bracket_ctor_args`.

### Tests that will prove it

Extend `test_generic_struct_local_linked_list.py`: assert `'int64_t it;' not in main`,
`'stubbed' not in _compile()`, and a build-and-run of `LinkedList[Int](1, 2, 3)` iterated with a
`for` loop printing `1 2 3` (compare against `tools/mojo`). Commands:
`python3 tools/memslot.py --gb 8 --label x -- python3 test_generic_struct_local_linked_list.py`.
Integrator owes `stdlib-syntax` `U` and `stdlib-dylib` skip count checks.

## Status (2026-11-01, round 3): PARTIAL — plan step 1 landed (typed Node pointee); step 2 (emit side) is the blocker.

### What landed (`elab_intu._eval_comptime_type_aliases`, `_erased_pointee_struct`; pin `test_node_pointer_alias_is_typed`)

An erased-word alias whose innermost argument is a generic struct at scalar
args (`_NodePointer = Optional[Pointer[Node[T], o]]`) now names the pointee's
mangled struct, enqueues it, and registers it from the spliced struct's own
file (`Node` lives beside `LinkedList`, so it was never in
`_imported_generic_structs`). `LinkedList_..._Int` now has `Node_1_T_3_Int *
_head/_tail` (was an erased word) and `Node[Int]` materializes in-TU.
Measured: gcc `-fsyntax-only` 0 errors on the probe and on `test_linked_list`,
`test_optional`, `test_deque`, `test_bitset`, `test_dict`, `test_list`,
`test_set`; stub counts equal to before except `test_linked_list` 213 -> 227
(Node's own method bodies are now emitted and hit the walls below).

### Still blocking (measured, not guessed)

1. `Node._prev/_next: Self._PointerType = Optional[Pointer[Self, o]]` are
   `int64_t`. Mapping the pointee `Self` to `mm.mangle(base, targs)` was
   tried: the field became plain `int64_t` (worse than the previous
   `int64_t *`), because the struct being materialized is not yet a registered
   name when its own field annotations are resolved. Needs the self name to be
   registered before field resolution (or a post-registration fixup).
2. Emit side (plan step 2) is not done and is the real wall: `x.value()[]`,
   `node[].next()`, `not p` on an `Optional[Pointer[Node]]` still lower through
   `mojo_list_get_int` (subscript-of-word) and the `int64_t.next() stubbed`
   path (19 `next`, 10 `prev`, ... = 66 stubs in the probe). `.value()` and
   `[]` on a struct-pointer-typed Optional/Pointer must be the identity,
   `not p` a NULL test, and `Self._NodePointer()` a literal 0.
3. Iterator (`IteratorType[...]` parametrized alias) and struct-valued
   elements: unchanged from the previous entry.

## Status (2026-11-01, round 4): PARTIAL — Node's own links are typed; emit side (plan step 2) and the iterator remain.

### What landed (`elab_intu._erased_pointee_is_self`, `module_gen.py` constructor self-assign pass; pin `test_node_links_are_typed_self_pointers`)

- `_eval_comptime_type_aliases`: `Optional[Pointer[Self, o]]` (a node's own link)
  names the struct being spliced (`mm.mangle(base, targs)`), nothing enqueued.
- Root cause of round 3's blocker 1 ("the field became plain `int64_t`"): NOT
  registration order. The layout walk did type `_prev/_next` `Node_1_T_3_Int *`
  (registered placeholders exist before fields resolve); the later
  constructor-`self.X = ...` evidence pass (`module_gen.py`, `can_override`)
  then replaced it, because its rule "a `<Self> *` field is an unknown-type
  placeholder, let evidence win" cannot tell the placeholder from an
  EXPLICITLY ANNOTATED self-pointer field. An explicit annotation now wins.
- Effect: `Node_1_T_3_Int` has `struct Node_1_T_3_Int * _prev/_next`; gcc
  `-fsyntax-only` 0 errors on the probe. Stub count unchanged (66): the emit
  side below is what removes them.

### Still open (unchanged from round 3 items 2-3)
Emit side: `.value()` / `[]` identity, `not p` NULL test, `Self._NodePointer()`
-> 0 for pointer-typed Optional/Pointer; the `IteratorType[...]` alias;
struct-valued elements. NOT run: gate / `stdlib-syntax` / `stdlib-dylib`
(the integrator's): the `module_gen.py` change affects any annotated
self-pointer field, so `stdlib-syntax` `U` and `stdlib-dylib` skip count are owed.

## Status (2026-11-01, round 5): PARTIAL — emit side for the typed Node pointer landed (66 -> 26 stubs); allocation API + iterator remain.

### What landed (`emit_methods.py`, pin `test_node_pointer_unwrap_is_identity`)

On a struct-pointer receiver whose struct has no such METHOD, `.value()` /
`.unsafe_value()` / `.take_pointee()` / `.unsafe_take_pointee()` with no
arguments is the identity (the pointer word; NULL = None), placed before the
callable-field rule. Root cause of the `mojo_fnptr_call_0` in
`_LinkedListIter.__next__`: `Node` has a FIELD named `value`, so
`curr.value()` was lowered as a call through that field. Probe stubs 66 -> 26;
gcc `-fsyntax-only` 0 errors; pin fails before, passes after.

### Remaining (26 stubs, measured)
1. Allocation API: `alloc(Layout[Node[T]].single()).unsafe_leak()` and
   `ThinAllocation(unsafe_owned_ptr=nn).unsafe_with_layout({count = 1})`
   (`single` 4, `unsafe_leak` 4, `unsafe_with_layout` 6). Needs a lowering of
   `alloc(Layout[S].single())` to a zeroed `sizeof(S)` allocation typed `S *`,
   and `ThinAllocation(...).unsafe_with_layout(...)` to a free of that pointer.
2. `it = l.__iter__()` still `int64_t` (`IteratorType[...]` parametrized
   alias; `_LinkedListIter.__next__` stubbed, 2).
3. One residual `Node.next()`/`prev()` each, struct-valued elements, and the
   reflection helpers (`FormatStruct`, `TypeNames`, `params`, `fields`).
NOT run: gate / stdlib-syntax / stdlib-dylib (integrator's); `emit_methods.py`
change affects any struct with a field named `value` called as `.value()`.

## Status (2026-11-01, round 6): PARTIAL — allocation API landed (26 -> 14 stubs); iterator + reflection helpers remain.

### What landed (`emit_calls.py`, `emit_methods.py`, `emit_stmts.py`, `elab_intu._rewrite_callees`; pin `test_node_allocation_api_is_lowered`)

- `alloc(Layout[S].single()).unsafe_leak()` -> one zeroed `S *` via the shared
  `_alloc_n_<S>` helper (`_lower_alloc_single_leak`, hooked in `_lower_method_call`).
- `dealloc(ThinAllocation(unsafe_owned_ptr=p).unsafe_with_layout(..))` -> `free(p)`
  (`_lower_dealloc_thin_allocation`; hooked in BOTH `_lower_call` and the
  statement fast path in `emit_stmts._gen_stmt_ExprStmt`, which never reaches `_lower_call`).
- `Layout[Node[Int]]` is an expression-body type, not an annotation site, so
  `_rewrite_callees` now names the materialized struct there; without it the
  element erased to `int64_t`.
- Probe: `single`/`unsafe_leak`/`unsafe_with_layout` stubs gone; gcc `-fsyntax-only` 0 errors.

### Remaining (14 stubs, measured)
`it = l.__iter__()` is still `int64_t` and `__next__` is stubbed (the
`IteratorType[...]` parametrized comptime alias, plan step 3 of the earlier
guide); one residual `Node.next()`/`prev()`/`__hash__`; reflection helpers
(`FormatStruct`, `TypeNames`, `params`, `fields`, `write_sequence_to`,
`_write_self_to`, `IteratorOwnedType`); struct-valued elements.
NOT run: gate / stdlib-syntax / stdlib-dylib (integrator's). `test_gimple.py`:
421 pass, 3 fail (`generator_mixed_yield_types_honest_fallback`,
`every_ast_mutation_site_invalidates_the_walk_memo` on coro.py/cpp_core.py/module_gen.py
sites, `func_state_snapshot_covers_reset_func`) -- none in files this change touches.

## Status (2026-11-01, round 7): PARTIAL — iterator materialized; `it = l.__iter__()` is a typed struct and `__next__` is a real call.

### What landed (`elab_intu._eval_parametrized_aliases`, `_eval_pointer_fields`, `module_gen.py` + `calls_shared._resolve_overload`; pin `test_iterator_local_is_the_materialized_iterator`)

- `_eval_parametrized_aliases`: `comptime IteratorType[iterable_mut: Bool, //,
  iterable_origin: ..]: Iterator = _LinkedListIter[downcast[T, Copyable],
  iterable_origin]` evaluates to the mangled `_LinkedListIter` instantiation
  (`downcast[X, _]` -> `X`, the alias's own origin parameter -> an erased
  `MutAnyOrigin`, infer-only `mut: Bool` -> `True`, `forward` left to its
  default via `bind_type_args`); every `Self.IteratorType[...]` mention is
  rewritten to it and it is enqueued.
- `_eval_pointer_fields`: an inline `var f: Optional[UnsafePointer[Node[Int], o]]`
  / `Pointer[LinkedList[Int], o]` FIELD annotation names the pointee's mangled
  struct (`_LinkedListIter.curr` is `Node_1_T_3_Int *`, `.src` is
  `LinkedList_..._Int *`); annotation sites only.
- Overload tie-break: `LinkedList.__iter__` has `var self` (`IteratorOwnedType`)
  and `ref self` overloads, identical after type erasure, so `l.__iter__()`
  took the first (owning, stubbed `int64_t`). Candidates now carry
  `self_owned` and `_resolve_overload` prefers a non-consuming overload among
  type-indistinguishable ties.
- Probe: `it` is `_LinkedListIter_... *`, `l.__iter__()` calls `___iter___0120be_2`,
  `it.__next__()` calls the materialized method; the `int64_t.next()/prev()`
  stubs are gone (stubs 59 -> 8). gcc `-fsyntax-only` was not re-run on the
  other stdlib tests this round (only the pin + `test_gimple.py`: 421 pass,
  the same 3 pre-existing failures).

### Remaining
1. 8 stubs in methods off the repro's path: `LinkedList.__hash__`,
   `IteratorOwnedType` (the `var self` iterator alias, same shape as the one
   landed but unparametrized via `Self.IteratorOwnedType` + a `where` clause),
   and the reflection helpers `write_sequence_to`/`_write_self_to`/`FormatStruct`/
   `TypeNames`/`params`/`fields`.
2. Struct-valued elements (`LinkedList[CopyCountedStruct]`).
3. End-to-end build-and-run of `1 2 3` against `tools/mojo`: `fire.py build` of
   the probe (link mode) did not finish in 10+ minutes in this light-worker
   session; the integrator should run it. The pin asserts only the generated C.
NOT run: gate / `stdlib-syntax` / `stdlib-dylib` (integrator's). `calls_shared`
tie-break affects any overloaded method with a `var self` twin; `stdlib-syntax`
`U` and `stdlib-dylib` skip count are owed.
