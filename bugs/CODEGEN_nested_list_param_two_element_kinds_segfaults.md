# CODEGEN: a list-of-lists parameter reached from BOTH a `list[list[int]]` and a `list[list[str]]` call site prints every row as an address

Found 2026-10-02 while fixing
`CODEGEN_nested_list_loop_target_loses_inner_elem_type` (deleted by
its fix). Its test program has to give the string and the integer cases
DIFFERENT enclosing functions, because this is what happens when they share
one, and that is why the doc's subject looked narrower than it is. Verified
pre-existing: identical output from a pristine `git archive HEAD` checkout of
the tree the fix landed on (`.tmp/base`, `git archive HEAD | tar -x`), so the
element-type fix neither caused nor cured it.

## What I ran

`.tmp/repro.py <program>`, which compiles with
`test_gimple_runner.compile_mojo_to_gimple_exe` (single-TU `compile_to_gimple`,
`gcc -fgimple`, `runtime/fire_runtime.c`) and diffs the binary's stdout and
exit status against CPython on the same text.

## What I saw

```python
def show(rows):
    for row in rows:
        print(row)

def main():
    show([[1, 2], [3, 4]])
    show([["a", "bb"], ["c"]])
main()
```

```
CPython  : [1, 2] / [3, 4] / ['a', 'bb'] / ['c']      exit 0
compiled : 4312995904 / 4312995968 / 4312996096 / 4312999424   exit 0
```

Every row prints as the decimal of its own `MojoList *`, and the int case that
was CORRECT on its own (`show([[1, 2], [3, 4]])` alone prints `[1, 2]` and
`[3, 4]`) is now wrong too. With an inner loop added instead of `print(row)`
the same program SEGFAULTS (exit -11) on the third call:

```python
def show(rows):
    for row in rows:
        for cell in row:
            print(cell)

def main():
    show([[1, 2], [3, 4]])
    show([["a", "bb"], ["c"]])
    show([[1, 2], [3, 4]])
main()
```

```
CPython  : 1 / 2 / 3 / 4 / a / bb / c / 1 / 2 / 3 / 4   exit 0
compiled : 2 / 3 / 4 then SIGSEGV                     exit -11
```

Both spellings are exit-0-wrong or a hard fault, and neither has a diagnostic.

## Why

The parameter's element type comes from `_param_elem_types[callee][pname]`,
recorded by `note_list_literal`'s cross-call walk
(`mojo/middle/infra_infer.py` / `module_gen.py`'s `_record_param_elem`) and
seeded into `gen._elem_types` by `emit_funcs.gen_func`'s `_pe` loop. Two call
sites that disagree — `('MojoList *', 'int64_t')` here and
`('MojoList *', 'char *')` there — have to JOIN into one C type, and
`int64_t` is exactly what the model's default already is, so the join is
indistinguishable from "no evidence" at the read.

Two separate consequences, and they are worth separating because a fix has to
address both:

1. **The repr.** `print(row)` on a `MojoList *` local goes to `_gen_print`'s
   `MojoList *` arm, which calls `gen._list_repr_call(aval)`. That helper asks
   `_nested_elem_types` / `_struct_slot_kinds` / `_tuple_slot_types` what the
   list holds. With the parameter's element type resolved to `int64_t`, the
   inner list's own `_list_repr_fn` is reached with no kind evidence, and a
   `MojoList *` slot read through the `int64_t` accessor prints the pointer.
2. **The fault.** The inner `for cell in row:` loop declares `cell` by
   `_elem_of('row')`. The same bad join leaves `row`'s element type
   uninformative, so `cell` is declared `int64_t` while the read goes through
   `mojo_list_get_int` — on the string call site that is a `char *` pointer
   stored into an `int64_t`, and the subsequent print dereferences it.

Neither is the doc's subject: its `note_list_literal` carrying and its new
`_carry_nested_elem_type` both work, and work for the single-kind program.

## Next step

`_record_param_elem`'s conflict rule, for a `MojoList *` element whose NESTED
element ctype disagrees across call sites. Two directions, both real work:

* **Join the nested kind instead of dropping it.** Where the element ctype is
  the same (`MojoList *` in both) and only the NESTED one differs, the honest
  answer is the kind that does not require a guess, and the consumers already
  have a runtime route for an ambiguous one: `mojo_list_get_boxed` plus
  `gen._boxed_vals` is what a heterogeneous list with its own per-slot kinds
  goes through (`_gen_for_list`'s `_maybe_kinds_vals` arm). That makes
  `print(row)` a tagged repr and `cell` a boxed word, both correct for either
  call site.
* **Or make the list record per-slot kinds at the boundary**, the way a
  heterogeneous literal already does, so there is nothing to join.

What is NOT acceptable is what happens now: the join silently becomes the
`int64_t` default, which is simultaneously "int rows" and "I know nothing",
and the two readings are then indistinguishable downstream.
