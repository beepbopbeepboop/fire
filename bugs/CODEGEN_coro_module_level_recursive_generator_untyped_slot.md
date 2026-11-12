# CODEGEN: a module-level recursive generator whose yielded parameter is untyped refuses

Filed 2026-11-12, split out of the nested recursive generator `getattr` bug
(its root cause, the compiled-generator refusal of a runtime-named `getattr`,
is fixed in 37c877f7c; the nested shape is pinned by
`test_gimple_generator_runner.py::nested_recursive_*`).

## What is still open

The same recursive generator, lifted to module level (no enclosing function),
still refuses. The nested form is fine; this is the form that the old doc's
option 1 (lift the capture-free generator) would have produced.

## Reproducer

```python
def walk(xs):
    for i, st in enumerate(list(xs)):
        yield xs, i
        for fld in ('body',):
            sub = getattr(st, fld, None)
            if isinstance(sub, list):
                yield from walk(sub)

def outer(body):
    return list(walk(body))

def main():
    for p in outer([1, 2]):
        print(p[1])
main()
```

CPython: `0` then `1`. Compiled through the test runner's program path
(`_build_generator_program`) it refuses with:

    cannot compile module: function(s) walk (generator function(s), contain a
    `yield`/`yield from`) ... Unsupported shape(s): walk: yields ['xs'], whose
    call sites do not all pass the same statically-known type (they disagree,
    or one of them the static scan could not type at all) ... a compiled
    generator has ONE fixed C value-slot ...

Note: `build_stdlib_dylib.compile_module_to_c(..., linkable=False)` returns C
for this same text (~43 KB). That is NOT the refusal this doc is about, so do
not use it as the pass criterion. The runtime program path is.

## Why

`xs` is yielded in a tuple slot. Its call sites are `walk(body)` (from
`outer`, a `[1, 2]` list) and `walk(sub)` where `sub` comes from
`getattr(st, fld, None)`. The static scan cannot type the `getattr` result, so
`_ambiguous_yielded_params` (mojo/middle/coro.py) returns `{'xs'}` and the A3
slot has no fixed C type.

## Exact next step

Pick one; the first is preferred:

1. Make the scan prove `xs`'s kind from the call sites that CAN be typed and
   treat the untypable `walk(sub)` call as a recursive call whose argument has
   the same kind as the parameter (a fixpoint over the call graph), so `xs` is
   a list of the same element type as `body`.
2. Box the untyped tuple slot with the `'l'` box kind already in
   `mojo_repr_boxed`, so the slot needs no static type. Costs a box per yield.

Test to add: the reproducer above, run through `_build_generator_program`,
expected stdout `0\n1\n` (`test_gimple_generator_runner.py`, next to
`nested_recursive_tuple_generator_runtime_getattr`). Also re-check
`mojo/middle/coro.py` still compiles (`test_selfhost.py::coro_module_compiles_to_c`).

## Related

- `CODEGEN_tuple_slot_zero_in_collected_list_prints_none.md`: a `0` in a tuple
  slot of `list(walk(...))` prints `None`. The reproducer above avoids it by
  reading `p[1]` one element at a time.

## Done when

The reproducer's runtime output matches CPython under the runner. Delete this
doc in the commit that lands it.
