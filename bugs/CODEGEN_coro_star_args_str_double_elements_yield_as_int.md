# CODEGEN: str/double elements of a `*args` coroutine parameter yield as int

## Symptom (2026-10-29, default A3 backend, exit 0, wrong output)

```
def words(*ws):
    for w in ws:
        yield w

def main():
    for s in words("alpha", "beta"):
        print(s)
```

prints `4333578984` / `4333578992` (pointer values) instead of `alpha` /
`beta`. A `double` variant (`def halves(*xs): for x in xs: yield x`, called as
`halves(1.5, 2.25)`) prints `1` / `2`: the bit pattern is printed as an
integer.

## What is right and what is not

Right (landed 2026-10-29 with the `*args` call-site packing): the caller stores
each element with its own C type's accessor, `mojo_list_append_str` /
`_double` / `_int` (`_pack_generator_star_args`, `emit_calls.py`), and the
body reads it back with `mojo_list_get_str` (the loop variable is `char *`,
as it should be).

Wrong: the yield. The generated A3 body is
`__mojo_coro_yield_i (__c, (int64_t)(void *)w)`: the yield kind for `w` is
`'i'`, so the pointer is yielded as an integer. For a plain (non-`*args`)
string list parameter the generator is not A3-eligible and takes the legacy
cpp path, so it is not a like-for-like comparison and does not show this.

## Cause (as far as read; not yet pinned to a line)

The yield kind of a name bound by a `for` loop over a list parameter is not
derived from that list's element kind. The element kind is recorded for the
parameter (`_mark_coro_param_elem_kinds` in `mojo/middle/coro.py`:
`kinds = {'ws': 'char *'}`, confirmed), but the yield lowering for `w` falls
back to the default `'i'`.

## Next step

1. In the coroutine yield lowering (`mojo/middle/coro.py`, the `yield` rewrite
   that picks `__mojo_coro_yield_i/_p/_d`), when the yielded name is the target
   of a `for` over a list parameter whose `env` entry is `('list', k)`, use the
   yield kind for `k`: `'p'` -> `__mojo_coro_yield_p`, `'d'` ->
   `__mojo_coro_yield_d`.
2. Tests: the two repros above in `test_gimple_generator_runner.py`, expecting
   `alpha\nbeta\n` and `1.5\n2.25\n`.
3. Check `grep -n "__mojo_coro_yield_" <generated C>` for both repros before
   and after.

Related: `bugs/CODEGEN_coro_list_param_int_element_loop_target_is_char_pointer.md`
(the int-element case: the loop variable itself is wrong there).
