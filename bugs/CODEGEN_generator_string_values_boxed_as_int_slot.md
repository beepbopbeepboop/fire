# Strings yielded over an inline `sorted(...)` are boxed into an `int64_t` value slot

Class: medium. Generator value-slot typing, plus the sorter chosen after a
runtime container probe. Found while closing
`bugs/CODEGEN_star_unpack_of_generator_expression_derefs_the_handle.md`: its
`## Symptom` program cannot pass until this is fixed.

## Symptom

    def main():
        print(list(p for p in sorted(["b", "a"])))

    main()

CPython prints `['a', 'b']`. Measured 2026-11-18, the compiled program exits 0
printing pointer words instead:

    [4309587664, 4309587656]           # exact values vary per run

It is not genexp-specific. A hand-written generator does the same under
`list(...)`:

    def g():
        for p in sorted(["b", "a"]):
            yield p

    def main():
        print(list(g()))          # [430..., 430...]   (CPython: ['a', 'b'])
        for x in g():
            print(x)              # prints a, b correctly
    main()

The `for` loop looks right only because the consumer is
`mojo_cstr_or_int_str`, which decodes a boxed pointer at run time. `list()`
does not: it appends through the generator's declared value slot.

With a local list instead of a literal the ORDER is wrong too:

    xs = ["b", "a"]
    print(list(p for p in sorted(xs)))     # compiled: ['b', 'a'], CPython: ['a', 'b']

And the star-unpack doc's program dies in the C runtime:

    texts = {"x": "1", "y": "2"}
    print(cat(*(f"{p}={texts[p]};" for p in sorted(texts))))
    # compiled: no output, exit -10 (SIGBUS); CPython: x=1;y=2;

`cat` receives the generator's values as `char *`; they are boxed pointer
words, so the first `out += p` walks an address as a string.

## Cause

Two adjacent gaps, both visible in the generated C.

1. **The value slot is `int64_t`, not `char *`.** For
   `for p in sorted(["b", "a"]): yield p`, the body is correct (`p` is
   declared `char *`, read with `mojo_list_get_str`), but the yield is

       _t10 = (int64_t)(void *)p;
       __mojo_coro_yield_i (__c, _t10);

   so `_generator_to_list` (`mojo/backend_gimple/emit_infra.py`) reads
   `api['value_ctype'] == 'int64_t'` and appends every value with
   `mojo_list_append_int`. The string pointer's bits become an integer slot.
   A `for` loop instead takes the runtime-tag path
   (`mojo_cstr_or_int_str`) and hides the same wrong slot.

   The yield-ctype analysis lives in `mojo/middle/coro.py` (`_static_env`,
   `_yield_kind`, `_CALLSITE_PARAM_KINDS`) and
   `mojo/middle/exprtypes.py::_generator_yield_ctype`. It
   resolves a bare list literal and a local list, but not the element kind of
   an inline pure call such as `sorted([...])` / `sorted(xs)`.

2. **A runtime-probed container is sorted as int64 slots.** When the
   generator is a lifted genexp and the iterable's container arrives as an
   untyped `int64_t` parameter, `_lower_builtin_sorted` calls
   `_resolve_container_kind` (no static kind), then `_materialize_as_list`,
   which emits the runtime probes (`mojo_is_registered_dict` /
   `_set` / `_list`, `mojo_iter_boxed_list`). For a dict that path does
   `mojo_dict_keys` and even `mojo_list_set_kinds_uniform(_t4, 'p')`, but the
   following sort is still the generic `mojo_sorted(_t19)` -- an
   int64-payload sort, so string keys are ordered by address. This is the
   `list(p for p in sorted(xs))` wrong-order case. The static element type
   recovered by the probe is not carried into the sort decision.

## Next step

1. In `mojo/middle/coro.py`, teach the yield-kind analysis that a pure
   iterable call passes its argument's element kind through:
   `_argkind` already answers `('list', elem_kind)` for a list literal and a
   bare list local, and `_yield_kind` for `sorted` / `reversed` / `list` /
   `tuple` of such a value should answer the same. Then the value slot
   becomes `char *` and `_generator_to_list` takes the
   `mojo_list_append_str` arm (`_KIND_TO_SLOT_CTYPE` already has `'p'`).
   Measure `list(g())` and `list(p for p in sorted([...]))` before/after.
2. In `_lower_builtin_sorted` (`mojo/backend_gimple/emit_calls.py`), when the
   argument was materialized by the runtime probe, use the materialized
   list's recovered element kind to pick `mojo_list_sorted_str` instead of
   `mojo_sorted` -- the same `gen._elem_types` lookup the statically typed
   `MojoList *` of `char *` already takes. Do not blindly assume `char *`:
   the probe can also be a list of ints.

## How to verify

Add to `test_gimple_runner.py` (compare with CPython, as
`test_gimple_matches_cpython` does):

    def cat(*parts):
        out = ""
        for p in parts:
            out += p
        return out

    def g():
        for p in sorted(["b", "a"]):
            yield p

    def main():
        xs = ["b", "a"]
        print(list(p for p in sorted(["b", "a"])))
        print(list(g()))
        print(list(p for p in sorted(xs)))
        texts = {"x": "1", "y": "2"}
        print(cat(*(f"{p}={texts[p]};" for p in sorted(texts))))
    main()

Expected: `['a', 'b']`, `['a', 'b']`, `['a', 'b']`, `x=1;y=2;`.
Before the fix: pointer words, pointer words, `['b', 'a']`, exit -10.
