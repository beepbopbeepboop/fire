# RUNTIME: a type-erased `bytes` value is misclassified as a string

**Area:** RUNTIME (`runtime/fire_runtime.c`). **Status: OPEN, measured
2026-10-19, PRE-EXISTING on `master`.** Found while fixing
CODEGEN_list_of_bytes_reads_the_struct_slots (the compiled
`list(b"cd")` reading the `MojoBytes` struct as its own slots, now
closed by the `MojoBytes *` arm of `_materialize_as_list` in
`mojo/backend_gimple/emit_infra.py`). That fix answers the STATICALLY
typed case; a bytes value whose type was ERASED (an unannotated function
parameter) still reaches the dynamic dispatch, and the runtime
discriminators there read the struct as a `char *` string.

## What I ran

```
$ printf 'def f(x):\n    print(list(x))\n\ndef g(x):\n    print(x)\n\ndef main():\n    f(b"cd")\n    g(b"cd")\n' > .tmp/lb_dyn.mojo
$ python3 fire.py run .tmp/lb_dyn.mojo
[99, 100]
b'cd'
$ python3 fire.py --jit .tmp/lb_dyn.mojo
[25699, 0]
P c
```

`unannotated` = the parameter arrives as an erased `int64_t` handle.
`list(x)` on it walks the `MojoBytes` struct as a string and answers a
plausible-looking list of garbage words; `print(x)` renders the struct's
memory as a C string (`P c` — fragments of the struct header). CPython
and the interpreter both say `[99, 100]` and `b'cd'`. Exit 0, no
diagnostic, on both.

## Why it matters

Every place that discriminates "is this erased handle a string" gets a
live bytes object wrong: `list(x)`/`tuple(x)`/`all(x)`/`any(x)`/
`enumerate(x)`/`x.join(...)` on an erased bytes, the repr of an erased
bytes, dict keys, ... The discriminator is a range test plus
non-membership in the container registries: `mojo_boxed_is_str`
(`runtime/fire_runtime.c:1298`) accepts ANY value in the [2 GiB, 2^47)
window that is not a registered list/dict/set and not a built box — and a
`MojoBytes *` is a live heap allocation registered in none of those three
regs, so it classifies as a string and is handed to `mojo_str_chars` /
`mojo_repr_str`, which walk the struct's own fields as a NUL-terminated
char string. The codegen-emitted generic repr walker
(`_mojo_generic_elem_repr`, emitted beside every `_mojo_repr_list`)
makes the same guess: any pointer-shaped word that is not a registered
list/dict falls to `mojo_repr_str`.

This runtime already knows the answer and does not ask it: every bytes
object is registered in `_reg_bytes` at `mojo_bytes_alloc` and never
removed (there is no `mojo_bytes_free`, so no stale entry), and
`mojo_is_registered_bytes` (`runtime/fire_runtime.c:2432`) is the
container-registry-family predicate for exactly this.

## The exact next step

Consult `mojo_is_registered_bytes` at the three discriminators, in this
order:

1. `mojo_boxed_is_str` (line 1298): return 0 for a registered bytes,
   alongside the existing list/dict/set/box exclusions — that is the one
   predicate whose comment already says a container of any kind is a
   different answer, and bytes is the container it never learned.
2. `mojo_iter_boxed_list` (line 8831): before the is_str arm, a
   registered bytes becomes its ints — the same
   `mojo_bytes_len`/`mojo_bytes_get` element source the static
   `MojoBytes *` arm of `_materialize_as_list` now emits — so
   `list(<erased bytes>)` agrees with the static path instead of
   raising.
3. The codegen-emitted `_mojo_generic_elem_repr` / the int64 print path:
   a registered bytes must not fall to `mojo_repr_str`; it reprs as
   `b'...'` through the existing bytes repr (the one `g(x)` uses when
   the value is still statically typed).

The cheapest measurement is the two-function probe above through
`fire.py --jit`, compared against `fire.py run`. When it is fixed, add
the `f(b"cd")`/`g(b"cd")` shapes to `test_runtime_diff.py` (a
CPython-comparable case) and delete this doc.
