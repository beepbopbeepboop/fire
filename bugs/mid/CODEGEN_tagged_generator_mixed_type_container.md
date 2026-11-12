# CODEGEN_tagged_generator_mixed_type_container: let a mixed tagged name hold a container

Class: **mid** (this doc lives in `bugs/mid/`).

## Parent

`bugs/hard/CODEGEN_tagged_generator_mixed_type_step4.md` (plan step 4, "remove the
refusal"). Steps 2 and step 2 parts 2-3 removed the refusal for `double` and
`char *`. This doc is what remains.

## Current state (measured 2026-11-11, HEAD 73076be07)

A name bound to a tagged generator word and also to a container is still refused:

```
def g():
    yield 1
    yield None
    yield 2
def main():
    x = [1, 2]
    for v in g():
        x = v
        print(x)
    print(len(x))
main()
```

gives `RuntimeError: 'x': a name bound to a tagged generator word ... cannot also
hold a value of another C type (str or float): the box cannot carry it; refused`,
raised from `mojo/backend_gimple/emit_stmts.py` (the simple-name arm, the
`is_non_int_c_type(vtype)` half of the refusal, which is true for any pointer type
ending in ` *`).

## Why it is not a one-line change

The box has constructors for an int, a bool, a double, a str (`mojo_box_from_str`),
None and a bytes/list kind-copy (`mojo_list_get_boxed`). It has no constructor for a
live container passed by value into a tagged name. A `MojoList *` / `MojoDict *` /
`MojoSet *` stored into the box as its word would be read back by the kind-'l' path
(`mojo_repr_boxed`'s nested-list arm), which reads the list's own kind row, not the
box. So the representation has to be decided first:

1. **Box the pointer with a new kind.** A `'c'` (container) box holding the
   container word, with `mojo_unbox_plain` / `mojo_word_is_none` / `mojo_repr_boxed` /
   `_len_of_boxed` each taught the kind. Smallest change to the read side.
2. **Refuse only the mixed shape at the source.** Keep the refusal, but as a
   diagnostic that names the two bindings, instead of a generic codegen refusal.
   This is an honest answer if no real program needs the shape.

The decision is needed before code. The measurement that decides it: grep the stdlib
and `test/` corpus for a generator whose loop variable is rebound to a container
(`x = v` where `v` is a container yield). If none, option 2 closes the doc.

## Tests that will prove it

- Option 1: the program above, CPython oracle, plus `len`, `print`, `==`, and a
  container-then-tagged order (`x = [1]; ...; x = v`). Add to
  `test_gimple_generator_runner.py`'s `run_tagged_for_target_bind_tests`.
- Option 2: `test_generator_refused` on the program above with the new diagnostic text.

## Status

Not started. Blocked on the decision above, which needs the corpus grep.
