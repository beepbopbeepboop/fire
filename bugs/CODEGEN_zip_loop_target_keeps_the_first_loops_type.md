# CODEGEN: a `zip`/`enumerate` loop target keeps the FIRST loop's declared type

Found 2026-10-02 while fixing
`bugs/CODEGEN_starred_rest_in_a_for_target_is_a_slot_named_star.md` (fixed
and deleted). It is a different defect in the same declaration machinery, and
it was found by writing the fix's own regression case.

## What I ran

```python
def main():
    for i, v in zip([1, 2], ["a", "b"]):
        print(i, v)
    for i, v in zip([1.5], [9]):
        print(i, v)
main()
```

    CPython:  1 a / 2 b / 1.5 9
    compiled: 1 a / 2 b / 1 [SIGBUS — exit -10, no third line]

No `*` in sight: this is the plain 2-slot zip target.

## Mechanism

`_declare_zip_slot` (`mojo/backend_gimple/emit_loops.py`) declares each slot
with its own sequence's element type and does NOT pass `force=True`, so
`_declare_var`'s first-decl-wins guard keeps the FIRST loop's declaration for
the whole function. The second loop then stores into it:

```c
i = (int64_t) mojo_list_get_double (...);   /* into an int64_t declared by loop 1 */
```

so `1.5` truncates to `1`, and the `print(i, v)` that follows formats an
`int64_t` with the string format the string-typed declaration implied — a
read of the wrong kind of slot, which is the SIGBUS.

`_gen_for_list` already fixed this exact hazard for its own targets, with a
long comment naming both halves (`_gen_for_list`: "a loop TARGET is not a read
of an existing name, so `_declare_var`'s first-decl-wins default is wrong
here — `for x in [1, 2]:` followed by `for x in ['p', 'q']:` REBINDS x"). The
zip/enumerate/zip_longest paths were never given the same treatment, so this
is the same bug in three lowerings that did not get the fix.

`_gen_for_enumerate` has it too, with the same program shape:
`for i, v in enumerate([1, 2]): ...` then `for i, v in enumerate([1.5]): ...`.

## Exact next step

1. In `_declare_zip_slot` / `_gen_for_enumerate` / `_gen_for_zip_longest`,
   pass `force=True` (or the `shadow_name`-or-retyped rule `_gen_for_list`
   uses) when the requested ctype differs from what the name is currently
   declared as. `_gen_for_list`'s `_fl_retype` condition is the model:
   `gen.var_types.get(var) not in (None, _fl_ctype)`.
2. Regression: a CPython-comparable `test_runtime_diff.py` case with two zip
   loops over differently-typed sequences under the SAME target names. It is
   deliberately not added to `for_target_starred_rest`, which uses distinct
   names per loop and would keep this bug hidden.
3. Check `_gen_for_set` / `_gen_for_str` / `_gen_for_bytes` for the same
   missing force — `_gen_for_set` already passes it, the other two may not.
