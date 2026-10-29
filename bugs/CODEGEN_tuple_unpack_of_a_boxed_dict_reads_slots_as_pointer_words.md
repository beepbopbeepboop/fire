# CODEGEN: unpacking a boxed dict prints its key pointers as decimal integers

Found 2026-10-29 while fixing the `(char)'p'` gcc -fgimple failure in
`CODEGEN_generator_function_Lib_mailbox.md` (the materialize-as-list dict arm
in `mojo/backend_gimple/emit_infra.py`).

## Symptom

```python
def ident(x):
    return x
class Box:
    def __init__(self, d):
        self._d = d
    def show(self):
        a, b = ident(self._d)
        print(a)
        print(b)
def main():
    Box({"k": 1, "j": 2}).show()
main()
```

CPython prints `k` and `j`. The compiled binary prints two large decimal
integers (the `char *` key pointers read as ints), exit 0.

The same wrong answer is pinned as the existing red test
`list_of_a_boxed_dict_materializes_keys_as_strings` in `test_gimple.py`
(`list(ident(d))` prints `[4345483616, 4345483632]` instead of `['k', 'j']`).
That test is red on master, before the `(char)'p'` change.

## Mechanism (measured in the generated C)

`_materialize_as_list` (the dict arm, `emit_infra.py` ~4115) does the right
thing for the list: `mojo_dict_keys` plus `mojo_list_set_kinds_uniform(result,
'p')` and `_maybe_kinds_vals.add(result)`. But the TUPLE-UNPACK statement
(`emit_stmts.py` ~1101-1230, the non-star branch) does not go through that
marker for an opaque RHS. It calls `gen._tuple_elem_value(vtype, v, i)` on the
boxed handle, and the generated code reads the slots with
`mojo_list_get_int(...)` (e.g. `_t17 = mojo_list_get_int (_t3, _t2);`
in `.tmp/kinds_unpack_method.c`), so the per-slot kind table is never
consulted for these reads.

## Expected

`a` and `b` print `k` and `j`, matching CPython.

## Next step

1. In the non-star tuple-unpack branch of `emit_stmts.py`, when the RHS is an
   opaque/boxed handle (`vtype == 'int64_t'`) and the value may be a
   container, read each slot with `mojo_list_get_boxed` (the reader that
   consults the per-slot kinds table), not `mojo_list_get_int`. Confirm the
   dict arm's kinds record is what the reader sees on the same temp.
2. Turn `list_of_a_boxed_dict_materializes_keys_as_strings` green, and make
   `tuple_unpack_of_a_boxed_dict_inside_a_method_builds` assert the printed
   keys (`k\nj\n`) instead of build-only. Both are in `test_gimple.py`.
3. Gate: `make check`, then `make gate` once at the end. The generator-suite
   tests `generator_pops_heterogeneous_tagged_stack` and
   `generator_pops_stack_two_level_tuple_unpack` are the regression guard
   for this area (see the docstring of
   `test_list_of_a_boxed_dict_materializes_keys_as_strings`).

Reproduce with `python3 test_gimple.py`. On the tree with the `(char)'p'`
fix, the two failures that remain are this doc's symptom
(`list_of_a_boxed_dict_materializes_keys_as_strings`) and
`ctor_of_a_container_reaches_the_comprehension`, which is a separate red
(the compiled stdout stops before the last line the CPython oracle prints)
also present on master, not investigated here.
