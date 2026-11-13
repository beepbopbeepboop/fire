# COMPILE_FAIL: `yield from` a nested generator — refusals stay refused, and tagged-kind delegation matches the compiled kind

Part 3 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4.md`
(SPLIT). Depends on part 1 (minimal nested-generator `yield from` in a coroutine generator; fixed in this tree), which provides the lookup this part tests the edges of.

## Goal

Once part 1 claims a nested generator for `yield from`, two things must hold.
First, a nested generator the capture model did NOT claim must still be refused
with its existing message. Second, a claimed nested generator that yields a
tagged (boxed) value must be delegated with the same slot kind it was compiled
with, so the delegating loop reads the value as the nested generator wrote it.

## Measurement needed first

* Negative cases. Write fixtures for: a rebound capture (the enclosing name is
  reassigned after the nested definition), a `nonlocal` write from the nested
  generator, and a keyword argument at the `yield from` call. Each should still
  produce the refusal it produces on master. Confirm that on master first, then
  check it is unchanged after part 1.
* Tagged case. Write a nested generator that yields both `int` and `str` (or
  `None`), captured and delegated to by `yield from`. Check whether the compiled
  output matches CPython. If it does not, the defect is the slot-kind handoff
  that part 1 lowers through `_record_generator_value_kind(api)` and
  `api['tagged']`/`value_ctype`. Record the measured result in Status before
  changing code.

## Plan

1. Add the negative fixtures to `test_nested_generator_yield_from_in_coroutine.py`
   as a `negative` case: each must refuse, and the refusal text must match the
   existing message. Also assert the message is the one that master produces.
2. Add a `tagged` fixture as a positive case if the measurement shows a
   mismatch, and fix the handoff in `cpp_core._cpp_yield_from` or
   `emit_calls._record_generator_value_kind`, reusing the existing kind
   bookkeeping. If there is no mismatch, add the fixture anyway as coverage and
   say so in Status.
3. Do not widen `_nested_generator_captures` or `_compute_nested_closure_captures`.

## Acceptance

* `python3 test_nested_generator_yield_from_in_coroutine.py negative` exits 0:
  each unclaimed shape is refused with the existing message.
* If the tagged fixture exposes a mismatch, `python3 test_nested_generator_yield_from_in_coroutine.py tagged` exits 0 and its output matches CPython.
* `python3 test_gimple_generator_runner.py` still passes.

## Done when

`python3 test_nested_generator_yield_from_in_coroutine.py negative` exits 0.
Run it under `python3 tools/memslot.py --gb 8 --label part4-part3 -- python3 test_nested_generator_yield_from_in_coroutine.py negative`.

## Out of scope

* The minimal shape: part 1. The main shape: part 2.
* The plain consuming `for x in <nested generator>(...)` path: part 5 of the parent (already fixed).
