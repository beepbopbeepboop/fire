# CODEGEN: a float+pointer mixed return now travels as a tagged word; container METHOD operations on that word still read it as an integer

Status: OPEN (follow-up). Filed 2026-11-12 by the round that fixed the
representation bug — a function returning a float on one path and a tuple/list/
str/None on another now returns the tagged word and every arm is boxed by kind
(see `git log --oneline` around this file's commit;
`test_float_return_beside_tuple_return.py` is its acceptance test and passes).
This doc is the part that fix does NOT cover, so the queue is not silent about
it. Its predecessor, the deleted CODEGEN_float_return_beside_tuple_return_not_converted.md,
was removed with that fix, as its own Done-when required.

## What landed (measured, this tree)

- `infra_infer._infer_return_type_core`: a return-type join of a `double`/`float`
  with a pointer becomes `int64_t`, and the body is recorded in
  `gen._float_mixed_return_bodies` (by body identity).
- `_gen_stmt_ReturnStmt`: each arm of such a function is boxed by kind —
  `mojo_box_from_double`, `mojo_box_from_str`, `mojo_box_from_list`,
  `mojo_box_from_bytes`, `mojo_box_from_bool`, `mojo_box_none` (new runtime
  helpers for the list/bytes forms). A pointer arm that is a dict/set/struct is
  REFUSED with a diagnostic naming the function, because a box of it would be
  rendered by the list repr.
- `module_gen` records callees in `_ret_may_hold_float`; `lower_expr` marks a
  call's result temp as `_boxed_vals` + `_tagged_word_vals`, and a simple bind
  keeps the box and marks the local's name.
- Consumers that dispatch by kind: `print`/`repr` (`mojo_repr_boxed`),
  arithmetic and comparison (`_tagged_arith_select` / `_tagged_cmp_select`),
  `is None`, list append (`mojo_list_append_word`, which now keeps a kind-'l'
  slot a container), `len` (`mojo_len_word`, kind-'l' arm added),
  subscript (`mojo_word_subscript`, new), slice (`mojo_word_slice` /
  `_word_slice_step`, box unwrap added), iteration, `str()`/f-strings,
  `isinstance(x, tuple/float)`, and list `+` concatenation.

Verified with `test_float_return_beside_tuple_return.py` (PASS; five programs,
compiled through `compile_mojo_to_gimple_exe`, run, compared with CPython) and
`python3 test_gimple_runner.py`: 615 passed, 6 failed on this branch. None of the
six is a mixed-return shape — three are `with`-statement exit cases, one is the
libm `math` case (which passes when run by itself), and two are `peek()`
Optional prints (`Optional(Some)` vs CPython's value, the existing niche).

## Still broken (each measured 2026-11-12 on this tree)

Program shape:

```python
def f(x: Int):
    if x == 0:
        return 2.5
    return [3, 4]

def main():
    t = f(1)
    ...
```

| statement | CPython | compiled |
|---|---|---|
| `t.append(5); print(t)` | `[3, 4, 5]` | SIGSEGV |
| `print(3 in t)` | `True` | `False` |
| `print(t.count(3))` | `1` | `0` |
| `print(t.index(4))` | `1` | `-1` |

Cause: these lowerings dispatch on the receiver's STATIC C type. The tagged
result is the erased `int64_t` (the whole point of the representation change),
so the method/`in` paths take their integer fallbacks instead of a list one.
`t[0]`, `len(t)`, `for v in t`, `print(t)`, `str(t)`, `t == [3, 4]`, `t + [5]`
and `isinstance(t, list)` are all correct, so the gap is specifically the
member-call and membership lowerings.

## Also still open: an ANNOTATED pointer return beside a float arm

A function whose `return` annotation fixes a pointer type (`-> String`) and
whose body still returns a float is deliberately not widened: the annotation
decides the C return type and the float arm keeps the old
`(int64_t)<double>` → pointer coercion (compiles, truncates; prints `1` for a
value that should be `1.5`). Pinned as the compilable spelling by
`test_float_into_pointer_return_regression.py`. Either the annotation should
win and the float arm be an error, or the tagged-word widening should override
a contradicted pointer annotation — a decision, not a mechanical change.

## Exact next step

1. Give the member-call (`emit_calls._lower_method_call`, list arm) and the
   membership lowering (`_lower_binary`'s `in`) the same runtime kind dispatch
   the subscript got: a tagged word is a list when it is a kind-'l' box or a
   registered list (`mojo_box_word` then `mojo_is_registered_list`), and the
   list arm of each operation is then the existing one on that pointer. A
   float/int/None word raises TypeError, as CPython does for `1 in 2.5`.
2. Add the four rows above to `test_float_return_beside_tuple_return.py`.
3. Then decide the annotated-return question above and either widen or refuse.

The self-host `fire.o` step (`python3 fire.py fire.py --dump-full`, then
`gcc -fgimple` on it) was NOT run by this round; it is the integrator's gate.
