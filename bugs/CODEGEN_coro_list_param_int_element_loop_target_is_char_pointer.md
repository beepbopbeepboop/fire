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

## Next step

Give "list of ints" its own positive marker, distinct from the "nothing known"
default, rather than reusing `int64_t`:

1. Decide the representation (a separate `gen._elem_known` set keyed by the
   parameter, or a sentinel element type). Audit every writer of
   `gen._elem_types[...] = 'int64_t'` first: `_boxed_list_ptr`'s rule exists
   because some of them are defaults.
2. `_mark_coro_param_elem_kinds` records the int element under that marker.
3. `_boxed_list_ptr` accepts the marker as evidence and takes the list path.
4. Tests: the repro above, the `*args` `t += x` shape, and a non-coroutine
   list parameter (must not change). This is a shared-rule change: run the
   full gate, and compare `stdlib-dylib`'s `skip` count before and after.

Related: `bugs/CODEGEN_coro_star_args_str_double_elements_yield_as_int.md`
(the same loop variable, but for `char *`/`double` elements, where the yield
side is wrong).
