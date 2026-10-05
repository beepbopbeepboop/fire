# CODEGEN: `print(x)` never frees the repr string it asked a walker for

## Status: `print(<container>)` FIXED 2026-10-04 — and the doc is KEPT for the consumers that are not

The `print` path is fixed and measured; four other consumers of the same
walker are not, and they are named below with what each one needs.

**What was wrong.** Not the free — that part already existed, and the `sprintf`
arm four lines below the leaking one had always done `free (t);`. What was
missing was knowing WHICH repr helpers a caller may free at all, and nothing
recorded it. Three of them return a string LITERAL on some arm
(`mojo_repr_bool`: `b ? "True" : "False"`; `mojo_bool_to_str`: `b ? t : f`;
`mojo_repr_float`: `"nan"`/`"inf"`/`"-inf"` on three of its four), and
`mojo_repr_boxed` inherits the third through its `'d'` arm. `free`ing a
literal is heap corruption rather than a leak, which is why this was not a
one-line change and why the doc says a wrong free here is a use-after-free.

**What landed.** `_OWNED_REPR_FNS` in
`mojo/backend_gimple/emit_infra.py`: a table of the helpers whose return the
caller owns on EVERY path, every name read body by body, with the five excluded
ones named beside it and the arm that excludes each. `_gen_print` routes all
nine repr-producing arms through `_own_repr`, which defers the release until
after the last `print_fn` call — the separator and newline prints read the
buffer in between, which is why the existing `_cstr_held` deferral beside it
exists.

**Measured, this tree, `/usr/bin/time -l` peak RSS:**

| loop count | before | after |
|---|---|---|
| 50 000 | 2.52 MB | 1.69 MB |
| 200 000 | 4.92 MB | 1.69 MB |

Flat at 16.4 B/iteration before, flat at nothing after. The existing
`gimple_printed_container_does_not_grow` (six shapes, 60 000 iterations)
drops from **10.9 MB to 1.7 MB**. New case
`gimple_printed_container_repr_is_released`: one shape, 200 000 iterations, a
3 MB ceiling chosen to sit between the two answers (1.6 MB with the free, ~5 MB
without — ~1.8x headroom each way), 0.7 s. That ceiling is the point of the
case: the existing one has 40 MB against ~9.6 MB of leaked buffers, which is why
this leak survived a test written to catch it.

## What is NOT fixed: the four consumers that do not consume at the call

`_stringify_value` is the ONE place that picks the walker for `print`, `str`,
`%s` and the f-string interpolation — which is why the doc says the fix has to
land where the two cannot disagree, and it does. But `_stringify_value`
*returns* its value to a caller that may keep it, so the release cannot live
there; it belongs at each consumer, and only `print` has one. Still leaking,
each for the same reason and each with the same one-line shape once its
consumer is identified:

| consumer | where | why it is not `print`'s fix |
|---|---|---|
| `f"{xs}"` | `emit_calls.py`'s f-string interpolation, beside `_stringify_value`'s other three callers | builds a concatenation, so the release is owed when the CONCATENATION is consumed |
| `'%s' % xs` | the `%`-formatting arm | same: `mojo_sprintf` copies out, but the walker result is one of its arguments |
| `str(xs)` | `_lower_builtin_str` | hands the value straight to the caller, which may store it — `s = str(xs)` is legal, so this needs the `note_fresh_result`/`is_fresh_container_operand` chokepoint `emit_infra.py` already has rather than an unconditional free |
| `repr(xs)` | the `repr` builtin | same as `str`, and the doc notes `x = print(xs)` does not exist but `s = repr(xs)` does |

`str` and `repr` are the two that cannot be an unconditional free, which is
exactly what the doc's "this needs the ownership chokepoint" said; the
chokepoint is `note_fresh_result` / `is_fresh_container_operand` /
`owned_free_fn_for`, and it is already used by the container-literal paths.

**Found 2026-10-02** while finishing the per-field remainder of
`PERF_printed_container_repr_leaks_its_cat_buffers.md` (whose Status now
records this as the residual that fix's own memory case still shows). Measured
on `work/bugs4-9-c`, and pre-existing on its parent — the fix for the struct
dump *reduced* this number rather than introducing it.

## What I ran

`test_gimple_runner.py`'s own bounded-memory harness, one shape per run, at two
loop counts a 4x apart (a single size proves nothing about a slope —
`doc/MEMORY.html` §8, which is why `tools/mem_slope.py` exists):

```python
# .tmp/plainn.py
def main():
    xs = [1, 2, 3]
    for i in range(NNN):
        print(xs)
main()
```

| loop count | peak RSS |
|---|---|
| 50 000 | 2.36 MB |
| 200 000 | 4.70 MB |

**16.4 B/iteration, flat.** Same shape on the struct-dump case: 80.4 B/iteration
against a 58-character repr, which is the size of the returned buffer.

## What I see

The generated `_gimple_main`:

```c
bb_4:
  _t10 = mojo_repr_list_ints (xs);   /* a fresh malloc'd buffer */
  mojo_print (_t10);
  _t11 = _slit_10000;
  mojo_print (_t11);
  goto bb_5;
```

`mojo_repr_list_ints` returns a buffer the caller owns, `_mojo_repr_list`'s own
body says so in the same file (`char *_buf = strdup(...)` returned at the end),
and nothing frees it. Compare the `%s`-style path a few lines away in other
generated programs, which DOES release what it formats:

```c
sprintf (_t9, _t11, _t8);
mojo_print (_t9);
free (_t9);
```

So the release protocol exists for a `sprintf`-built string and is missing for
a walker-built one.

## What I expected

`free` after the `mojo_print` that consumed it — the same transient-value
protocol `mojo_int_str_transient` + `_release_transient_cstr_args` already
implements for an Int dict key, and the same shape `_mojo_repr_list` uses for
the per-slot strings *inside* itself.

## Why it is still here

`print`'s argument is a lowered VALUE the program may also use afterwards
(`x = print(xs)` does not exist, but `s = repr(xs)` does, and a walker result
assigned to a name is the same value), so this needs the ownership chokepoint
rather than an unconditional free. `emit_infra.py` already has the two halves:
`note_fresh_result` records "this value is fresh for whoever consumes it next"
and `is_fresh_container_operand` + `owned_free_fn_for` decide who may free it.
What is missing is the *call* that emits the free after the consuming
`mojo_print`, for the walker arm of `print`/`str`/`repr`/`f-string`.

**Exact next step.** In the `print`/`str`/`repr` lowering in
`mojo/backend_gimple/emit_calls.py` (where the walker is chosen by
`_list_repr_fn` and friends), when the chosen arm is a walker call rather than a
`sprintf`, register the result as fresh (`note_fresh_result`) and emit the
release through the existing `owned_free_fn_for`/`owned_push_fn_for` pair after
the one call that consumes it — the same protocol `_cstr_key_src` +
`_release_transient_cstr_args` implements, with the same "exactly ONE call
consumes this" contract. Careful: the `f"{xs}"` and `str(xs)` spellings route
through `_stringify_value`, which SHARES this decision with `repr`, so the fix
has to land where the two cannot disagree.

**Not fixed in the commit that found it** because it is a different subsystem
(the print/format release protocol) from the struct repr's per-field ownership,
and because a wrong free here is a use-after-free that
`MallocScribble` turns into a wrong answer. It is worth 16 B per container
print today and scales with the printed width.

## Why the existing memory test does not see it

`gimple_printed_container_does_not_grow` prints SEVEN shapes 60 000 times
against a 40 MB ceiling and measures 12.8 MB. Six hundred thousand prints at
~16 B is ~9.6 MB of leak inside a budget that the fix's own headroom already
consumed, so the case passes with the leak present. That is the doc's own
argument about ceilings applied to a test: a ceiling loose enough that a real
slope fits under it measures nothing. The tripwire that would catch this is a
tighter ceiling on the same case, or a two-size slope on one shape — not a
bigger loop at the same budget.