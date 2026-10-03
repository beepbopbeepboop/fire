# PERF: every printed container leaks its intermediate `mojo_str_cat` buffers (~500 B per `print` of an 8-element list)

Found 2026-10-01 while fixing `bugs/CODEGEN_tuple_dict_key_hashed_by_address.md`
(deleted with that fix): the fix put a dict KEY's renderer on the same repr
walkers, so what was a slow leak on a debug print became a per-lookup leak, and
fixing it named the rest of the family. Standard:
`bugs/PERF_memory_over_4gb_is_a_bug.md`.

## What I ran

```console
$ python3 -c "import test_gimple_runner as T; T.test_gimple_bounded_memory(
      'probe', open('prog.py').read(), <stdout>, 40)"
peak RSS 99.7 MB (limit 40)
```

`prog.py` is `xs = [1,2,3,4,5,6,7,8]` and `for i in range(200000): print(xs)` —
200 000 prints of an 8-element list, so ~500 B per print. The same program
with a string key instead of a tuple key peaked at 10.8 MB, which is what a
non-leaking loop of that shape costs; the compiler-emitted `_mojo_repr_list`
and the runtime's `mojo_repr_list_*` family are both reached from `print`.

## Mechanism

`mojo_str_cat(a, b)` allocates a NEW buffer and deliberately leaves both
arguments alone (`runtime/fire_runtime.c`). Every repr walker is a chain of it:

```c
    char *_buf = strdup("[");
    for (...) {
        if (_i > 0) _buf = mojo_str_cat(_buf, ", ");   /* the old _buf is leaked */
        _buf = mojo_str_cat(_buf, mojo_repr_int(...));  /* and so is this slot's */
    }
    return mojo_str_cat(_buf, "]");                     /* and this _buf */
```

An N-element list leaks N+1 buffers per repr, each sized to the text so far.

## What is fixed, and what is not

Fixed in the same commit as the tuple-key fix, for the two walkers that commit
put on the key path: `mojo_repr_list_kinds` (whose per-slot strings were leaked
as well as its buffers) and the new `_container_key_str`. Both go through a
`_cat_free(a, b)` helper (`runtime/fire_runtime.c`) that releases the left
operand, and the measurement that motivated it is pinned by
`gimple_tuple_dict_key_lookup_does_not_grow` in `test_gimple_runner.py`
(1.7 MB peak, was 93.6 MB before).

**Not fixed**, and this doc is the record: the other walkers, in two places that
must both change for a program to stop leaking.

1. `runtime/fire_runtime.c`: `mojo_repr_list_ints`, `mojo_repr_list_doubles`,
   `mojo_repr_list_bools`, `mojo_repr_list_bytes`, `mojo_repr_list_intlists`,
   `mojo_repr_list_pairs`, `mojo_repr_list_pairs_s`, `mojo_repr_list_pairs_d`
   — all the same shape, so `_cat_free` plus a `free()` of each per-slot string
   is mechanical. `mojo_repr_obj` returns a SHARED static and must stay on the
   right of the cat.
2. `mojo/backend_gimple/module_gen.py`: the EMITTED `_mojo_repr_list` (line ~817)
   and `_mojo_repr_pair` (line ~864), plus `_mojo_repr_set` in the same
   preamble. These are C source text emitted into every generated program, so
   `_cat_free` has to be reachable from there: either promote the helper to
   `mojo_str_cat_free` in `fire_runtime.h` (a public entry point, so
   `test_runtime_header_scan.py`'s expected set needs it) or emit a local
   `static char *_cat_free` in the same preamble. The second keeps the runtime
   header unchanged, and it is what I would do — but it means the same helper
   exists twice, in two languages, which is why the choice is worth making
   deliberately rather than by default.

A `print` of a container in a loop is not an exotic program: it is what a
compiler's `--dump` does, what a logging path does, and what the leak hunt's own
instrumentation would do to itself.

## Next step

Do (2) first, since it is the copy every generated program carries, then (1).
Both are behaviour-preserving apart from the memory, so the standard for this
one is byte-identical generated C before vs after: `cmp` the artifact for a
program that prints a list, a nested list, a set and a pair.
