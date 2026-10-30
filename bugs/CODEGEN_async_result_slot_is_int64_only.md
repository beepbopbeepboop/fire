# CODEGEN_async_result_slot_is_int64_only: a float or string async return is awaited wrong

## Status (2026-10-29 — partial: typed result slot landed for same-module callees; cross-module / untraced handles still read the int slot)

The stack-switch async lowering (`mojo/middle/coro.py`, `_lower_one_async`)
used to declare every async unit's result slot `int64_t`, so a `return 1.5`
was awaited as `1` and a `return "s"` came back as its pointer printed as a
number. The slot is now typed by the unit's one return kind:

- `_async_result_kind(fn)` picks 'i' / 'b' / 'p' / 'd' from the `return`
  values (`_async_return_kinds`, shared with the refusal). 'b' is `_Bool`; a
  mix of 'b' and 'i' is 'i'.
- Each `return` writes through `_ASYNC_SETRET_SHIM[kind]`
  (`__mojo_gen_set_return_d` / `_p` bit-cast into the int64 box; 'i'/'b' keep
  `__mojo_gen_set_return`).
- The awaiting side reads the raw slot and bit-casts it with
  `_async_result_read` (`__mojo_bits_d` / `_b` / `_p`), keyed by the callee's
  kind: `_result_kind_of` answers from `_register_async_result_kinds`, which
  maps every async def in the module (nested and methods too) and every
  variable bound from one (or from `create_task(...)`) to its kind, before any
  unit is lowered. A name two defs give different kinds is refused.
- Read sites covered: `await f(...)`, `await task^` / `await <task var>`,
  `asyncio.run(f(...))`, `asyncio.run(var)`, `<task>.wait()`. Type inference
  for `await f()` already followed the callee's `value_ctype` through
  `_await_call_ctype`, so `print(await f() ...)` picks up the float type.
- A mix that cannot share one slot (`return 1` with `return "s"`, or
  `return 1.5` with `return x`) is still refused: "disagree on one kind".

Measured on this branch (stack-switch harness, `test_async_void_return.py`):
`print(await f())` for `-> Float64` prints `1.5`; `print(asyncio.run(f()))`
prints `2.25`; a `String` return prints `s`; a bool return prints `True`;
`create_task` + `await t` / `t.wait()` / a bound `asyncio.run(c)` all carry the
float.

Still missing (the remaining gap, and the next step):

- An awaited or driven handle whose origin is NOT in this module still reads
  the int64 slot: `create_task(imported_async())` and `await <expr>` where the
  callee is defined in another module. `_result_kind_of` answers 'i' for
  these, so a float there is still awaited as its truncated integer. The fix is
  to carry each module's async result kinds across the import boundary (the
  same channel `_async_api` / the module spec uses for `value_ctype`), then
  read it from that registry. Until then a local-only refusal would be wrong
  for the int-returning imports that work today.
- The `'p'` (string) slot stores a pointer into the int64 box. The value is
  whatever pointer the callee returned; a `return` of a string computed in the
  coroutine frame would outlive that frame. Same lifetime question as the
  generator value channel; not measured here.

Pinned by `test_async_void_return.py`: `test_async_float_and_int_returns_refused`,
`test_async_mixed_return_kinds_refused`, `test_async_same_kind_returns_still_compile`,
and the four typed-result round trips (`test_async_float_result_*`,
`test_async_string_result_awaited`, `test_async_bool_result_prints_as_bool`).
The harness is `test_coro_future_await._build_and_run`, which now takes the
shim names it expects in `require=`.

Related: `bugs/CODEGEN_generator_function_Lib_test_test_frame.md` (its t3
entry records the same mixed-return finding and the refusal, which still holds).
