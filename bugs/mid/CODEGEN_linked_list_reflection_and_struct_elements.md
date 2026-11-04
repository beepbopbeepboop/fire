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
3. End-to-end build-and-run of the probe printing `1` against `tools/mojo`
   (`fire.py build` in link mode did not finish in a light-worker session).
   Integrator: run it; the pin only checks the generated C.

Owed by the integrator: `stdlib-syntax` `U` and `stdlib-dylib` skip count.
