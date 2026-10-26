# CODEGEN: `list(<a runtime-built pair list>)` loses the pair repr

**Area:** CODEGEN (`mojo/backend_gimple` + the repr selection in
`mojo/backend_gimple/emit_infra.py`). **Status: OPEN, measured
2026-10-19, PRE-EXISTING on `master`.** Found while fixing
CODEGEN_list_of_bytes_reads_the_struct_slots; both shapes below were
reproduced with PURE LIST inputs, so this is independent of bytes and of
that fix — it shows up whenever the pair list is built at RUNTIME
(`enumerate`/`zip`) and copied through an outer `list(...)`.

## What I ran

```
$ printf 'def main():\n    e = enumerate([7, 8])\n    print(list(e))\n    print(e)\n    print(list(enumerate([7, 8])))\n' > .tmp/p4.mojo
$ python3 fire.py --jit .tmp/p4.mojo
[[None, 7], [1, 8]]
[(0, 7), (1, 8)]
[(0, 7), (1, 8)]
$ python3 fire.py run .tmp/p4.mojo
[(0, 7), (1, 8)]
<enumerate object at 0x...>
[(0, 7), (1, 8)]
```

```
$ printf 'def main():\n    z = zip([1, 2], [3, 4])\n    print(z)\n    print(list(z))\n' > .tmp/p5.mojo
$ python3 fire.py --jit .tmp/p5.mojo
[(1, 3), (2, 4)]
[4378492608, 4378492672]
```

Two surfaces, one family:

* The enumerate shape: the copy prints the pairs with LIST brackets and
  the first pair's `0` as `None` — the generic repr's None-sentinel
  heuristic, which `mojo_repr_list_pairs` exists precisely to avoid.
* The zip shape: the copy prints each pair's POINTER as a decimal.

Discriminating facts: the UNCOPIED value prints right in both
(`print(e)`, `print(z)`), and a LITERAL list of pairs copies right
(`x = [(1, 3), (2, 4)]; print(list(x))` → `[(1, 3), (2, 4)]` on the
compiled path). Only a pair list built at runtime loses its pair-ness in
the copy.

## Why it matters

`enumerate`/`zip` results are the canonical "list of pairs" values, and
`print(list(z))` / `print(list(e))` is the most natural way to show one.
The compiled path answers with `None`s and pointer decimals and exits 0 —
plausible-looking garbage, the silent wrong-answer class.

## The mechanism (measured in the generated C)

The outer `list(...)` lowers through `_lower_ctor_from_iterable` to a
synthetic comprehension whose loop copies each pair WORD into a fresh
list. The source's NESTED pair typing (`gen._nested_elem_types` =
`['int64_t', ...]` — what `_list_repr_fn` consults to route to
`mojo_repr_list_pairs`) is not carried onto the copy, so repr selection
falls back and picks the wrong helper per surface:

* enumerate: the copy's elements are recorded `MojoList *`, no nested
  entry → the generic codegen walker `_mojo_repr_list`, whose pair
  predicate requires the runtime TUPLE MARKER (`mojo_is_tuple`) — and the
  pairs the ENUMERATE lowering builds in emitted C are never
  `mojo_mark_as_tuple`'d (unlike `mojo_zip`'s, per the generated walker's
  own comment), so the predicate misses and the pair walks as a plain
  list with the None sentinel.
* zip: the copy's elements are recorded `int64_t` (the raw slot word of a
  `void *`-typed zip result), so `_list_repr_fn` routes the copy to
  `mojo_repr_list_ints`, which reads every slot through
  `mojo_repr_int` — the pair pointer prints as a decimal.

## The exact next step

Carry the nested element typing through the comprehension copy, so the
copy routes to `mojo_repr_list_pairs` the way the uncopied value does:
when the comprehension's iterable carries a 2-slot nested spec, record it
on the fresh result (mirroring what the `set`/`dict` arms already do with
`gen._elem_types`/`gen._nested_elem_types` on their temps). As a
separate, smaller half: the enumerate lowering should `mojo_mark_as_tuple`
each pair it builds in emitted C, so the generic walker's pair predicate
recognizes enumerate pairs the way it already recognizes zip/dict-items
pairs — without that, `print(e)` stays right only by the luck of the
nested record on the enumerate result's own name. Pin both shapes
(enumerate and zip, copied and uncopied) in `test_runtime_diff.py`, and
delete this doc when the copied shapes agree with CPython.
