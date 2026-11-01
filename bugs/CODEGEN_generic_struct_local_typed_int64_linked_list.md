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
