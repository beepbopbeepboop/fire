# CODEGEN: `print(x)` never frees the repr string it asked a walker for

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