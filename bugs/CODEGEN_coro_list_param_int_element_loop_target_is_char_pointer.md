# CODEGEN: a coroutine's loop over an int-element list parameter is typed `char *`

## Symptom (2026-10-29, default A3 backend, exit 0, wrong output)

```
def gen_add(xs):
    for x in xs:
        yield x + 100

def main():
    for v in gen_add([4, 5]):
        print(v)
```

prints `4345762336` / `4345762352` (pointer values) instead of `104` / `105`.
Same defect for a `*args` parameter: `async def total(*xs)` with
`var t = 0; for x in xs: t += x`, awaited as `total(1, 2, 3)`, returns a
pointer. Yielding or printing `x` unchanged is correct (the yield kind is
int); only arithmetic on the loop variable is wrong.

## Cause

The A3 coroutine body reads a list parameter through a boxed `int64_t`
handle, so the ordinary `for` lowering emits the runtime dict-or-list dispatch
(`mojo/backend_gimple/emit_loops.py`, `_gen_for_iter`). Both arms bind one
shared loop variable, and the dict arm declares it first, as `char *`.

The positive-evidence rule that would skip the dead dict arm,
`_boxed_list_ptr` (`emit_loops.py`, ~line 698), treats an element type of
`int64_t` as "nothing known" and returns None. The producer,
`_mark_coro_param_elem_kinds` (`mojo/middle/coro.py`), has the evidence
(`env` = `('list', 'i')`) but skips `int64_t` on the grounds that it is "the
default the loop target assumes anyway". That comment is wrong for this path:
the dispatch wins. The two halves disagree about what `int64_t` means.

Verified: making `_mark_coro_param_elem_kinds` record `int64_t` does not fix
it, because `_boxed_list_ptr` still discards the entry. Reverted; not a fix.

## Status (2026-10-30)

Landed (the marker the old next step asked for, as a per-body name set rather
than a new `_elem_types` sentinel):

- `mojo/middle/coro.py` `_mark_coro_param_elem_kinds` records int-element list
  params as `_mojo_coro_param_int_lists` instead of dropping them. `_elem_types`
  is unchanged, so `int64_t` still means "nothing known" for every other writer.
- `mojo/middle/coro.py` `_lower_one_async` now applies the same marker as
  `_lower_one` does for generators. Before this, a plain `async def` had no
  cross-call element contract at all.
- `mojo/backend_gimple/module_gen.py` folds that into `_coro_int_list_params`
  (per body, like `_coro_str_params`).
- `mojo/backend_gimple/emit_loops.py` `_boxed_list_ptr` accepts the marker as
  positive evidence, so both `for` and `enumerate` take the list path.
- Tests: `test_coro_list_param_int_element.py`. Pre-fix, the generator repro,
  the `*args` generator, and the async `*args` body all fail; the plain-list
  control passes both before and after. Post-fix all five pass. The
  `enumerate` case already passed before the fix and is kept as a guard.
  `test_coro_future_await.py` (18/18) and `test_coro_detached_async.py` (2/2)
  pass.

Still open:

- The async `*args` shape is verified structurally only. Its value is not yet
  seen printed: `--jit` drops an `async def main`'s output, `asyncio.run(total(...))`
  on this form reports "a coroutine was expected", and `.wait()` does not link.
  Those are separate gaps. Next step: find a compiled driver that prints the
  awaited result, and assert `6` for `total(1, 2, 3)`.
- The full gate was not run here (the integrator's job). It is a shared-rule
  change, so compare `stdlib-dylib`'s `skip` count before and after.
- Doc is kept, not deleted, until the async value is seen end to end.

Related: `bugs/CODEGEN_coro_star_args_str_double_elements_yield_as_int.md`
(the same loop variable, but for `char *`/`double` elements, where the yield
side is wrong).
