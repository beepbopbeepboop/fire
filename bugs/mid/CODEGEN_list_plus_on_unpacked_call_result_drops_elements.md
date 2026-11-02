# CODEGEN: `a + b` of two lists bound by unpacking a call's tuple result drops the elements

Found 2026-11-02 while fixing the self-host crash from the boxed tuple-unpack read
(`_tuple_elem_value`'s `mojo_list_get_boxed`, commit 1bfc82a09).

## Symptom

```python
def hoist(stmts: list):
    hoisted = []
    maps = {}
    for s in stmts:
        if len(s) > 1:
            hoisted.append(s + "!")
            maps[s] = len(s)
    return stmts, hoisted, maps

def main():
    out, nested, maps = hoist(["a", "bb", "ccc"])
    both = out + nested
    print(len(both))     # CPython: 5, compiled: 0
main()
```

Iterating, printing and `len` of `out`/`nested` are right (test
`gimple_unpack_of_a_returned_list_list_dict_tuple`). Only `+` is wrong.

## Cause

The unpack targets are bound from `mojo_list_get_boxed`, so they are `int64_t` words
(`_boxed_vals` / `_dyn_word_vals`) with no static container type. `+` of two `int64_t`
operands is integer addition of the two pointers unless `_is_may_hold_str_param` says the
operand may hold a string; and `mojo_add_words` (runtime) only knows str+str, otherwise
integer add.

## Next step

1. `mojo_add_words` (runtime/fire_runtime.c): if both words are `mojo_is_registered_list`,
   return the concatenation (the list-concat entry point `+` on `MojoList *` uses).
2. emit_exprs `_lower_binary_tail` `+` arm: route two `int64_t` operands that are dyn words
   (`_dyn_word_vals` / `_boxed_vals`) through `mojo_add_words`, not only may-hold-str params.
3. Add the `both = out + nested; print(len(both))` lines (expect `5`) to the test above.
Gate: compile_stdlib `FAILED: U` must not rise (a `+` on ints must stay integer add).
