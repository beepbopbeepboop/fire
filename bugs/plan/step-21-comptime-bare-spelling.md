# plan/step-21: the bare `comptime <expr>` diagnostic

**Source:** `bugs/FORMAL_known_limits.md` §7.
**Master plan:** `doc/finish-formal.md` §"Step 21".

## Goal

The one genuine silence in the `comptime` parity table. The bare spelling
`comptime expr` yields `0` and prints nothing, where the parenthesised form
prints "unavailable in compiled mode". The fix is in the **lowering**, not the
parser.

## Constraints (why no parser guard)

`comptime <expr>` is real and the stdlib uses it —
`std/algorithm/reduction.mojo:251`, `std/math/math.mojo:630`,
`std/memory/stack_allocation.mojo:142`, `std/reflection/reflect.mojo`. A parser
guard took `compile_stdlib.py` from 664/0 to 660/4, so it was reverted. The
fix belongs in `mojo/backend_gimple/`.

## What to add

- Give the bare spelling the same `unavailable in compiled mode` diagnostic the
  parenthesised spelling emits.
- Turn `test_comptime_parity.py`'s NOTE into a hard check for the bare spelling,
  and keep the parenthesised spelling's hard check.

## Structure-only rule

A guard that breaks working code is worse than the bug; do not touch the parser
or `_CONV_KWS`. `U` must never increase in `compile_stdlib.py`.

## Files

`mojo/backend_gimple/`, `test_comptime_parity.py`.

## Verification

`test_comptime_parity.py`; `compile_stdlib.py` still 664 passed / 0 unexpected.

## Done when

- [ ] the bare spelling prints the diagnostic
- [ ] the four stdlib modules still compile
- [ ] the parity test asserts the diagnostic, not a silence

## Dependencies

None.
