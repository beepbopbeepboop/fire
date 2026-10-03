# A `*rest` element in a for-loop target is lowered as a slot literally named `*rest`

**Area:** CODEGEN (the GIMPLE backend's per-slot unpack in
`mojo/backend_gimple/emit_loops.py::_gen_for_list`). Found 2026-10-01 on
`work/bugs3-codegen-2-r2` while fixing
`bugs/CODEGEN_for_loop_target_one_tuple_vs_paren_single_name.md` — a different
defect in the SAME target representation, found by the same test program, and
**not fixed there** because it is a new feature rather than a wrong answer to
a question the compiler already answers.

## What I ran and what I saw

```
$ cat .tmp/forloop/c2.mojo
def main():
    for first, *rest in [(1, 2, 3), (4, 5, 6)]:
        print(first, rest)

$ python3 .tmp/forloop/c2.py     # CPython 3.14, with main() appended
1 [2, 3]
4 [5, 6]

$ python3 fire.py run .tmp/forloop/c2.mojo      # the interpreter
1 [2, 3]
4 [5, 6]

$ python3 test_runtime_diff.py --case <this shape>
  FAIL  stdout line 5: interp='1 [2, 3]'  jit='1 0'
```

So the interpreter is right, the compiled path prints `1 0`. Exit 0, no
diagnostic.

## The generated C says exactly what is wrong

`gimple_codegen.compile_to_gimple(src, do_imports=False)` on that source:

```c
  int64_t *rest;                       /* the declaration            */
  ...
  _t19 = (MojoList *)_t20;
  _t21 = mojo_list_get_int (_t19, 0);
  first = _t21;
  _t22 = mojo_list_get_int (_t19, 1);
  *rest = _t22;                        /* the assignment             */
  ...
  _t23 = (int64_t)0;  /* ct param or undeclared: rest */
```

Two defects, and the first is what makes the second invisible:

1. **The `*` is part of the slot name.** `_gen_for_list` takes
   `gen._split_top_level_comma(inner)` and uses each element as a variable
   name verbatim, so the slot is `*rest`. The emitted declaration
   `int64_t *rest;` is C's pointer declarator reached by accident, and the
   assignment `*rest = _t22;` **dereferences an uninitialised pointer**. It
   did not segfault here (the slot lands in whatever the frame held), which is
   the worse outcome: a store through a wild pointer that happens to be mapped.

2. **A starred slot gets ONE element, not the remainder.** Even with the
   name fixed, `mojo_list_get_int(_t19, 1)` binds `rest` to the second element
   rather than collecting elements 1..n-1 into a list. Python's extended
   unpacking says `rest == [2, 3]`, and `mojo/middle/boundnames.py`'s
   `_lbn_target_names` already agrees: it strips the `*` and binds the name
   after it, because "a starred leaf binds the name after the `*`" is a
   binding rule, not a spelling.

The body's `rest` then reads as 0 with the codegen's own
`/* ct param or undeclared: rest */` note, which is the diagnostic this
project's conventions say must not be a silent wrong answer.

## Why it is pre-existing and not a regression from the for-target fix

`for first, *rest in ...` parses to the target string `'(first, *rest)'`, and
`for_target_is_tuple` and `target_slots` both answer exactly what they answered
before: two slots, `['first', '*rest']`. The star was already reaching
`_gen_for_list` verbatim. The fix for the 1-tuple changed which *question* the
loop lowerings ask about a target, not what they do with a `*`.

## Exact next step

In `_gen_for_list` (and the same per-slot loop in `_gen_for_dict`,
`_compr_list_loop` and the enumerate/zip paths, which share the shape):

* find the starred slot **by position**, not by scanning the name — the
  interpreter's `_bind_comprehension_target` already does this and its
  `before` / `star` / `after` arithmetic is the model to follow
  (`myinterpreter.py`, the `star_idx` branch);
* declare `rest` as `MojoList *`, initialise it with `mojo_list_new ()`, and
  append elements `star_idx .. len(item)-1` from the item's own accessor, so
  its element type is chosen by the same per-slot rule the non-starred slots
  use;
* a starred slot in a position other than the last is a CPython `SyntaxError`
  ("multiple starred expressions in assignment"), so the refusal is a
  compile-time one and belongs at the parser or at the top of the unpack, not
  in the emitted C.

Verify with `test_runtime_diff.py --case`: a program that iterates
`[(1, 2, 3), (4, 5, 6)]` and prints `first, rest`, and the same shape through
a dict (`for k, *vs in d.items()`) and a comprehension
(`[r for first, *r in pairs]`), each diffed against CPython. The compiled path
must agree with the interpreter, which is already right.

## Evidence

- Generated C quoted above: `compile_to_gimple(..., do_imports=False)` on the
  3-line program.
- `mojo/backend_gimple/emit_loops.py:1700-1715` (`_gen_for_list`'s `is_tuple`
  branch and `var_names`), now reading `gimple_ctypes.for_target_is_tuple` /
  `gimple_ctypes.target_slots`.
