# A `_Bool` (or `int`) is cast to a pointer: `x and y` / `x or y` with mixed operand types

Class: medium. One lowering to change; the checker counts the result.

## Symptom

Building the compiler with the GCC front end prints, for example:

    mojo/backend_gimple/emit_stmts.py:1499:12: warning: cast to pointer from
    integer of different size [-Wint-to-pointer-cast]

The emitted statement is a pointer made from a 1-bit or 32-bit value:

    _t75 = _t74 == 0;          /* _Bool */
    _t64 = _t75;
    ...
    _t76 = (MojoList *)_t64;   /* a _Bool cast to a list pointer */

## Measured 2026-11-14

`tools/gimple_lint.py` has the rule `cast-narrow-int-to-ptr` (in
`mojo/ir/verify.py`). Over the compiler's own 188 sources it reports 167
findings (9 in `__GIMPLE` functions). Over the 12-file ratchet corpus,
`python3 test_gimple_lint.py ratchet` reports 13, and
`BASELINE['cast-narrow-int-to-ptr']` in `test_gimple_lint.py` is 13. It may
only shrink.

To list them for one file, from an empty directory outside the tree:

    python3 /path/to/tree/fire.py --dump /path/to/tree/mojo/middle/comptime.py
    python3 /path/to/tree/tools/gimple_lint.py -v --code cast-narrow-int-to-ptr comptime.ci

## Cause

Two source shapes produce every finding looked at so far:

    if isinstance(p, str) and p:          # mojo/middle/comptime.py:530
    if not (f(a) or g(b)): ...            # mojo/backend_gimple/emit_infra.py:3978

In `a and b` / `a or b` the operands have different types (`_Bool` and
`char *`, or `_Bool` and `MojoList *`). The lowering picks ONE result type
for the chain (the pointer type) and casts the short-circuit operand to it.
For `and` the short-circuit value is false, so the cast makes a null
pointer and the result is still falsy. For `or` the short-circuit value is
TRUE, so the cast makes the pointer `(T *)1`: truthy, and a crash if
anything dereferences it.

## Fix

Find where the boolean chain's merged result is typed and assigned (search
`mojo/backend_gimple/emit_exprs.py` for the `BoolOp` / `and` / `or`
lowering, and `_safe_coerce_emit` calls in it). Then:

1. When the chain is used only as a condition (`if`, `while`, `not`, an
   operand of another `and`/`or`), give the merged result the type `_Bool`
   and convert each operand with a truth test (`ptr != 0`), not a cast.
2. When the chain's VALUE is used and the operand types differ, the result
   is a boxed word (`int64_t`), with each operand boxed the way a mixed
   `if`/`else` expression already is. Never cast `_Bool` to a pointer.

Do not hide the finding by widening the `_Bool` to `int64_t` before the
pointer cast: `(T *)1` is the bug, not the width.

## How to verify

1. `python3 test_gimple_lint.py ratchet` reports fewer than 13; lower
   `BASELINE['cast-narrow-int-to-ptr']` to the new count in the same commit.
2. `python3 test_gimple.py` keeps its pass count with 0 failed. Add a case:
   `x = flag or names` (a `bool` and a `list[str]`), then `print(x)` for
   both values of `flag`, compared with CPython.
3. `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` passes.

## Done when

The baseline entry is 0 and removed, and this file is deleted in the same
commit (then `python3 tools/dangling_doc_refs.py --ratchet`).
