# LinkedList[T]: off-path methods still stubbed; struct-valued elements refused; no end-to-end run

Split from the (now fixed) `LinkedList[Int]` local-typed-`int64_t` bug: `var l =
LinkedList[Int](1, 2, 3)`, `l.__iter__()` and `it.__next__()` now lower to the
materialized structs and real calls (pin `test_generic_struct_local_linked_list.py`).

## Remaining (measured 2026-11-01 on the probe in that test)
1. 8 stubs in methods off the repro's path: `LinkedList.__hash__`,
   `IteratorOwnedType` (the `var self` iterator alias: `Self.IteratorOwnedType`
   with a `where` clause, same shape as the parametrized `IteratorType` alias
   already handled in `elab_intu._eval_parametrized_aliases`), and the
   reflection helpers `write_sequence_to`/`_write_self_to`/`FormatStruct`/
   `TypeNames`/`params`/`fields`.
2. Struct-valued elements (`LinkedList[CopyCountedStruct]`) are refused by the
   scalar-argument gate in `elab_intu._positional_bracket_ctor_args`; register
   the element's imported non-generic struct before the materialized methods'
   annotations resolve, then lift the gate.
3. End-to-end build-and-run of the probe printing `1` against `tools/mojo`.
   **Measured 2026-11-05: it was never slow, it crashed** - see Status.

Owed by the integrator: `stdlib-syntax` `U` and `stdlib-dylib` skip count.

## Status 2026-11-05 — end-to-end build run for the first time; three of its five blockers fixed

`fire.py build` of the probe never "did not finish": `driver.compile_program` raised
`IndexError: list index out of range` on `gen._link_needs_cxx_box[0]` (the end-of-compile cleanup
added with the resource-blowup work cleared EVERY `_`-prefixed container on the generator, the
link results included), so `fire.py build` silently fell back to its slow inline pipeline. Fixed
(`gimple_codegen._PIPELINE_RESULT_ATTRS`; pinned by `test_compile_linked_result.py`). Through the
driver the build now compiles in seconds and fails at LINK, which is the real end-to-end state:

Fixed here (pinned by `test_linked_list_link_symbols.py`):
- `LinkedList_..._Int___init__`, `..._pop`, `..._maybe_pop` undefined: the run-time class table and
  `_mojo_classattr_read` named an overloaded method by its bare symbol; they now use each method's
  overload id (first overload per name).
- `mojo_index` undefined: `index(i)` on an integer is now the integer (`emit_calls`).

Still undefined (the whole remaining link failure):
- `int64_t_unsafe_write` (from `append` / `insert`) and `int64_t__get_ref_with_unsafe_interior_origin`
  (from `get_nth`): a local annotated `Pointer[Node[Self.ElementType], MutUntrackedOrigin]`
  (`linked_list.mojo` 381/405: `var addr: Pointer[Node[Self.ElementType], ...] = alloc(...)`;
  `addr.unsafe_write(node^)`) is typed `int64_t`, so the method call lowers to a free function on
  `int64_t`. It is the same erasure the five failing pins in
  `test_generic_struct_local_linked_list.py` / `test_linked_list_hash_step1.py` name
  (`int64_t.next() stubbed` x9, `int64_t.unsafe_with_layout() stubbed`): a `Pointer[<materialized
  generic struct>, o]` annotation and an `Optional[Pointer[Node[T], o]].value()[]` deref resolve to
  the word, not to `Node_1_T_3_Int *`. Those five tests fail identically on the commit before this
  round; they are this item's quick tests.
- Next step: in `elab_intu`'s annotation rewrite, after `Self.ElementType` -> `Int`, resolve
  `Pointer[Node_1_T_3_Int, o]` to the struct pointer for LOCAL variable annotations (struct fields
  already do: `_head` / `_tail` are typed), and lower `p.unsafe_write(v)` on a struct pointer as a
  store through it and `p.value()[]` as a load. Then re-run the end-to-end probe
  (`driver.compile_program`, expect `1`).
