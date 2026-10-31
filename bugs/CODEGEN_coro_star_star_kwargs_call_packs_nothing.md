# CODEGEN: keyword arguments to a generator/coroutine with `**kw` are not packed

## Symptom (2026-10-29, default A3 backend, wrong output then crash)

```
def g(n, **kw):
    yield n
    yield len(kw)

def main():
    for v in g(3, b=5, c=6):
        print(v)
```

prints `3`, then segfaults (rc -11) at `len(kw)`. Expected `3` / `2`.
On a clean HEAD export the same program crashes before printing anything, so
this is pre-existing and was not introduced by the `*args` packing work.

## What the generated C does

The start call is `__mgco_g_start(3, 5)`: the keyword value `5` (for `b=`)
is passed RAW into the `**kw` slot, and `c=6` is dropped. The body then
reads `kw` as a handle (`mojo_is_registered_dict(5)` is false, falls into the
set/list arms) and crashes. The body's own dispatch is correct; the call
site is not packing the keywords into a `MojoDict`.

## Cause (read, not yet pinned)

`_emit_generator_start_call` (`mojo/backend_gimple/emit_calls.py`) packs
keyword arguments into a `MojoDict` only at the slot named by
`gen._func_kwargs_slot` (`_gen_kwslot`). That table is populated by
`module_gen.py`'s pre-pass walk (~line 7040), which does not record a
coroutine's `**kw` slot. So `_gen_kwslot` is -1 and the pad loop pops the
keyword values into the positional slots in call-site order.
`_emit_generator_start_call` and the method site in `emit_methods.py`
(`_lower_method_call`, which has no kwargs-slot handling at all) are both
affected.

## Next step

The same shape as the `*args` fix that landed with this doc
(`star_slot`, `mojo/middle/coro.py`):

1. Record `'kwargs_slot'` in the coroutine meta (`_lower_one`,
   `_lower_one_async`, `_lower_one_async_gen`) as the C-signature index of the
   `**` parameter, or None, using the same `lead` arithmetic as `_star_slot`.
   Carry it into `api` in `register()`.
2. In `_emit_generator_start_call`, when the api has a kwargs slot, use it in
   place of the `_func_kwargs_slot` lookup (keep the lookup as the fallback for
   ordinary generators), so the existing `_pack_kwargs_dict` branch fires.
3. Mirror in `_lower_method_call` (`emit_methods.py`), which needs the
   kwargs-slot branch added: the slot index must include the receiver.
4. Tests: the repro above (expects `3\n2\n`), and a method variant, in
   `test_gimple_generator_runner.py` next to `run_star_args_call_tests`.
5. Before this lands, check the `**kw` case with NO keyword arguments
   (`g(3)`): the slot must be an empty dict, not 0 (a 0 is a null handle).
