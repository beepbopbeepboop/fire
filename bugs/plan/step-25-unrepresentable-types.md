# plan/step-25: representing `Error` and the unrepresentable type constructors

**Source:** `bugs/FORMAL_known_limits.md` §3 (the `Error` row: 6 files, "not a
frame problem at all").
**Master plan:** `doc/finish-formal.md` §"Step 25".

## Goal

`Error` is in `model.UNREPRESENTABLE_TYPE_CTORS`: a `String` and an
`Optional[StackTrace]` is not one word, so there is no argument to give it,
frame or otherwise. The doc's measurement: `Error("boom")` with a literal
argument is refused too, with an equally accurate message — "the type has no
representation whichever you hand it". A frame address is not what stops these
six.

## What to add

Either:
- **a representation** (a boxed `Error`, a pointer to a heap/frame record — a
  capability on the value model), with a differential row; or
- **a refusal** that states the type has no representation on this path.

The step decides from the measurement, not from the spelling, and states which.
A refusal is the doc's leaning, but a representation is the real fix if a
construct needs it.

## Structure-only rule

Do not assert a shape the image cannot see; the message must state the one thing
it has checked. Scaffold any proof obligation with `sorry` (ledger).

## Files

`formal/model/` (`UNREPRESENTABLE_TYPE_CTORS`, `type_constructor_prefers_local_
struct`), both codegens, `test_formal_optional.py`, `test_formal_run.py`.

## Verification

`test_formal_optional.py`, `test_formal_run.py`; the six files re-measured.

## Done when

- [ ] `Error("boom")` either builds (with a differential row) or refuses with a
      reason true of the type
- [ ] the `DType`/`String()` over-refusal guards stay green
- [ ] the six files' verdicts are re-measured

## Dependencies

step-10 (the `String` half is the same collision).
