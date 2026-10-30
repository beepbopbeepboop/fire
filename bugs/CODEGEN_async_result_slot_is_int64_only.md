# CODEGEN_async_result_slot_is_int64_only: a float or string async return is awaited wrong

## Status (2026-10-29 — partial: mixed/float returns REFUSED; typed result slot NOT built)

The stack-switch async lowering (`mojo/middle/coro.py`, `_lower_one_async`)
declares every async unit's result slot as `int64_t`
(`'value_ctype': 'int64_t', 'value_kind': 'i'`) and writes each
`return <value>` with `__mojo_gen_set_return(__c, e)`. The awaiting side
reads the bits back as an integer. Exact for an int; wrong for anything else.

Measured on this branch (`fire.py build`, then run the binary):

```
async def f() -> Float64:
    return 1.5
async def amain():
    print(await f())        # prints 1          (CPython: 1.5)
```

```
async def f(x: Int):
    if x > 0:
        return 1
    return "s"
async def amain():
    print(await f(0))       # prints 4367193456 (CPython: s)
```

Landed (partial, honest): `_async_return_refusal` makes both of these a
whole-module refusal (`cannot compile module: ...`), in `_lower_one_async`,
which every async unit passes through. Mixed known kinds and any float return
are refused; same-kind returns and unresolved (hole) returns are unchanged.
Pinned by `test_async_void_return.py`
(`test_async_mixed_return_kinds_refused`, `test_async_float_return_refused`,
`test_async_same_kind_returns_still_compile`). A refusal loses a program that
ran wrong; it does not make the program right.

Still missing (the real fix):

- A typed async result slot. Plan: infer the unanimous return kind the way
  `_generator_value_kind` infers a yield slot (`_yield_kind` over the
  `ReturnStmt` values, nested defs skipped), set `value_kind`/`value_ctype`
  in `_lower_one_async`'s `meta` from it, and carry a `double` through the
  int64 slot by bit-cast (the same convention `__mojo_gen_arg_d` uses for
  params). The `__mojo_gen_set_return` call site must bit-cast a `'d'` value
  and the await read must cast back.
- The awaited expression's TYPE must follow the slot. `await f()` is typed
  today as int64 wherever exprtypes sees an `AwaitExpr`; without that the
  bit-cast alone still prints a float as an integer. Find the AwaitExpr
  typing in `mojo/middle/exprtypes.py` and key it off the callee's recorded
  async result kind.
- Strings: a `'p'` return currently round-trips through the int64 slot as a
  pointer and is NOT refused. Whether that is correct depends on the awaiting
  side casting back to `char *`; measure with a single-kind `return "s"` before
  deciding whether `'p'` joins the refusal or gets a typed slot.
- A bool return prints as `1`, not `True` (the slot is `'i'`). Same fix
  (typed slot with a `'b'` kind), not refused, because it is not a silent
  numeric change.

Quick test for the full fix: the `async def f() -> Float64` repro above prints
`1.5`. Then `test_async_float_return_refused` is dropped in the same commit (it
pins a refusal of a shape that will now compile). The mixed-kind refusal stays:
one slot cannot honestly carry an int and a string return, typed or not.

Related: `bugs/CODEGEN_generator_function_Lib_test_test_frame.md` (its t3
entry records the same mixed-return finding and the refusal).
