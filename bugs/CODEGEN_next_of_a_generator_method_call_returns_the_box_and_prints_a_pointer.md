# `next(<a call to a generator method>)` computes the right value and then loses its type

## What was run

```sh
python3 fire.py build .tmp/g8/m.py && ./g8      # the distilled repro below
```

## What was seen

```python
class Box:
    def __init__(self):
        self.n = 0

    def render(self):
        yield "a"
        yield "b"


def use_meth(b):
    return next(b.render())


def main():
    print(use_meth(b))
```

```
compiled: 1 / 4297170656 / 1
CPython:  1 / a        / 1
```

Exit 0, no diagnostic, and `4297170656` is the address of the yielded
`'a'` — a `char *` formatted as a decimal.

## What is actually right, and where it stops

The **generated C is correct**. `use_meth`'s body is the full drive:

```c
_t1 = __mgco_Box_render_start (b);
_t2 = __mgco_Box_render_resume (_t1);
...  if (_t2) goto bb_3; else goto bb_4;        /* StopIteration path */
_t4 = __mgco_Box_render_value (_t1);
```

So the method-call form of the generator handle is already lowered — there is
no missing capability here, and `_generator_method_api`'s registration is
found and used. The top-level form (`next(gen())`) is right too, in both the
1-arg and the `next(gen(), default)` spellings.

The break is one step further on, in **type inference at the `return`**: the
function's inferred return type is `int64_t`, so

* the C signature is `int64_t use_meth(Box *)`,
* the caller's `print` sees an `int64_t` with no `_actual_types` entry and
  formats it with `mojo_str_from_int`.

`_quick_type` resolves `b.render()` to `MojoGenerator *`
(`mojo/middle/resolve_shared.py`'s `(_ssn, _smeth) in
gen._generator_method_api` row), but it has no row for `next(...)` — so
`_infer_return_type` types `return next(b.render())` as the scalar box and
the real `char *` is laundered through it. `_generator_yield_ctype` already
computes the right answer for the same generator (`api['value_ctype']`,
`char *` here) and `_lower_generator_next` uses it at the `next` site, so the
answer exists; it is simply not consulted when the `next` call's own type is
what is being asked for.

## Why it is filed rather than fixed

The pre-pass that would need it (`_collect_return_types`) runs before
`_generator_method_api` is populated for every method, so the fix has to
decide where to source the value type: re-deriving it from the method's body
at return-inference time, or deferring the return type the way
`func_return_types` is already deferred for callees. Both are real work, and
the second touches the function-signature machinery, which is exactly the
area `bug:CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered` and
`bug:CODEGEN_next_on_bound_list_iter_cursor_off_by_one` (other workers) also
sit in. Taking it from here would mean three workers in one file's generator
handle path.

## What it is NOT

* Not a missing `next(<generator method>)` lowering — that path works, and the
  C above is the evidence.
* Not `CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered` (a struct
  with `__next__`, no generator at all) or
  `CODEGEN_next_on_bound_list_iter_cursor_off_by_one` (`next()` of a REBOUND
  list-iterator local). This one is the return-type inference after a
  successful drive.

## Next step

1. A `_quick_type` row for `next(<expr>)` that resolves the argument to a
   generator api (`_generator_api`, `_generator_method_api`,
   `_imported_generator_bindings`, `_fn_returns_generator`) and answers
   `api['value_ctype']` — falling back to today's box when no api is
   visible, so nothing that works today changes.
2. That needs the api tables populated before return inference, so measure
   first whether `_collect_return_types` already runs late enough; if not,
   `_infer_return_type` already has a `_generator_yield_ctype` dependency for
   the yield side, so the ordering question has a precedent to copy.
3. Regression shape: this program, compared against CPython — and with the
   top-level `next(gen())` and `next(gen(), default)` forms in the same case,
   so the three spellings are pinned together and a fix cannot make the
   method form right by making the others wrong.