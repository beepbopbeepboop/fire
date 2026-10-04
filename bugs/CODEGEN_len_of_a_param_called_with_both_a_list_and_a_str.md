# CODEGEN: `len(x)` on a parameter whose call sites are BOTH a list and a string reads a MojoList header as a C string

Found 2026-10-02 while writing the regression case for
`bugs/CODEGEN_string_arg_type_lost_across_forwarding_hop.md` (fixed and
deleted). It is a different slot — the answer is decided by what the
PARAMETER is typed, not by who forwards it — and it is non-deterministic,
which is how it stayed invisible.

## What I ran

```python
def lst(x):
    return len(x)

print(lst([1, 2, 3]))
print(lst("abcd"))
```

| run | `lst([1, 2, 3])` |
|---|---|
| CPython 3.14 | `3` |
| compiled, run 1 | `5` |
| compiled, run 2 | `5` |
| compiled, run 3 | **`3`** |
| compiled, run 4 | `5` |
| compiled, run 5 | `5` |

The generated C is `int64_t lst (char * x) { return mojo_strlen (x); }` with
the list argument arriving as `(char *) _t5` — a `MojoList` struct pointer
reinterpreted as a NUL-terminated string, so the answer is whatever bytes
follow the list's data pointer in the heap. A value comparison could never
catch this: it is right some of the time.

## Mechanism

`lst`'s parameter is called with a list literal and a string literal, so the
evidence is `{MojoList *, char *}` — not unanimous, and
`_gmi_apply_call_site_param_evidence` (which only resolves the str-vs-container
ambiguity) declines it. What types it `char *` instead is the free-function
Pass 1.3d's own resolution or a name-based fallback; either way one C type per
slot means a genuinely polymorphic parameter gets ONE of them, and `len()`
lowers against that one type rather than against the value.

`print(x)` on the same parameter is already handled honestly: the value is
routed through `mojo_cstr_or_int_str`/`mojo_cstr_or_int_len`, which asks
whether the int64_t is a plausible pointer before treating it as a string.
`len()` is the member of that family that has no such guard.

## Exact next step

1. In the `len()` lowering (`emit_calls.py`'s builtin `len`, or
   `_gen_for_*`'s per-element `mojo_list_len` where `len` of a str reaches it),
   consult the same discriminator `print` uses before committing to
   `mojo_strlen`: an int64_t that is not a plausible pointer, or that is a
   registered `MojoList`/`MojoSet`/`MojoDict`, is a container and must be
   measured with `mojo_list_len` / `mojo_set_len` / `mojo_dict_len`.
   `_is_may_hold_str_param` is the sound input for the "may be a string"
   direction; the container direction needs the runtime's own registries,
   which is what `_repr_boxed_container` already calls for the same reason in
   `_gen_print`.
2. Regression: this program's exact shape, run at least 8 times and required
   to agree every time (`test_gimple_stdout_repeated` is the helper — a
   single-run assertion passes two times in five, which is the whole trap).
   It belongs next to the sibling mixed-type rows in
   `test_gimple_runner.py`, and the `lst("abcd")` line is in the program so a
   fix cannot simply type the parameter as a container.