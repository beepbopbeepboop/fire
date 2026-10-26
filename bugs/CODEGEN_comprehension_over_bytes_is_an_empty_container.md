# CODEGEN: a comprehension over `bytes` is an empty container

**Area:** CODEGEN (`mojo/backend_gimple`). **Status: OPEN, measured
2026-10-19, PRE-EXISTING on `master`.** Found while fixing
CODEGEN_list_of_bytes_reads_the_struct_slots (the compiled `list(b"cd")`
reading the `MojoBytes` struct as its own slots, now closed by the
`MojoBytes *` arm of `_materialize_as_list` in
`mojo/backend_gimple/emit_infra.py`). That fix routes `list(b"...")` and
`tuple(b"...")` through the shared materialization; `set(b"...")` and
ordinary comprehensions do NOT route through it, and they are still broken
by this, a different gap in a different function.

## What I ran

```
$ printf 'def main():\n    print(set(b"ab"))\n    print([x for x in b"ab"])\n    print({x for x in b"ab"})\n' > .tmp/p1.mojo
$ python3 fire.py run .tmp/p1.mojo
{97, 98}
[97, 98]
{97, 98}
$ python3 fire.py --jit .tmp/p1.mojo
set()
[]
set()
```

All three shapes: the interpreter and CPython give the bytes' ints, the
compiled path gives an EMPTY container and exits 0 — the silent
wrong-answer class. The `for`-loop form is NOT affected: `for x in b"ab"`
already works on the compiled path (`emit_loops._gen_for_bytes`,
`mojo/backend_gimple/emit_loops.py:2481`), and `list(b"cd")`/`tuple(b"cd")`
work after the materialization fix — only the comprehension dispatch is
missing the arm.

## Why it matters

`set(b"...")` and `[x for x in b"..."]` are plain, ordinary expressions,
and the compiled path answers them with an empty container and exits 0.
The `set` constructor reaches this the same way every other non-list
iterable does: `_lower_ctor_from_iterable` (`mojo/backend_gimple/emit_calls.py:4174`)
builds a synthetic `{x for x in <arg>}` and hands it to
`_lower_comprehension`, whose dispatch chain
(`mojo/backend_gimple/emit_exprs.py:6328` — the `is_range` /
`MojoList *` / `MojoStr *` / `char *` / `MojoDict *` / `MojoSet *` /
`MojoGenerator *` arms) has NO `MojoBytes *` arm, so a bytes iterable
falls to the `/* TODO: comprehension over <type> */` fallback, which
emits nothing: an empty result with no diagnostic. A real comprehension
over a bytes value (`[x for x in b"ab"]`) hits the identical missing arm
directly.

## The exact next step

`_lower_comprehension` needs a `MojoBytes *` arm beside its other
container arms. Two shapes, in order of preference:

1. Materialize the bytes through the `MojoBytes *` arm that
   `_materialize_as_list` gained in the fix above (a `MojoList *` of
   ints via `mojo_bytes_len`/`mojo_bytes_get`), then dispatch to the
   existing `MojoList *` arm — the same move
   `_lower_ctor_from_iterable` already makes for an opaque
   `list(...)`/`tuple(...)` argument, so no second iteration scheme.
   Add `'MojoBytes *'` to `_COMPREHENSION_ITER_TYPES`
   (`mojo/backend_gimple/emit_calls.py:4168`) in the same change, and
   keep that tuple in sync with the dispatch chain (its own comment
   demands it).
2. A direct index loop mirroring `_gen_for_bytes`, if shape 1 turns out
   to lose element-type records the comprehension arms need.

The cheapest measurement is the three-line probe above through
`fire.py --jit`. When it is fixed, the `set(b"ab")` line belongs in
`test_runtime_diff.py`'s `bytes_iterates_as_ints` (or a sibling case),
and this doc is deleted.
