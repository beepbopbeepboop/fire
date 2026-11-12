# CODEGEN: a 0 in a tuple slot of a list collected from a generator prints None

Filed 2026-11-12 while landing the nested recursive generator getattr fix
(`bugs/CODEGEN_coro_nested_recursive_generator_getattr.md`). Related to, but the
reverse of, `bugs/mid/CODEGEN_tagged_tuple_slot_none_prints_zero.md` (there a
`None` reads back as `0`; here a `0` reads back as `None`).

## Reproducer

```
def walk(xs):
    for i, st in enumerate(list(xs)):
        yield xs, i
def outer(body):
    return list(walk(body))
def main():
    print(outer([1, 2]))
main()
```

CPython: `[([1, 2], 0), ([1, 2], 1)]`
Compiled: `[([1, 2], None), ([1, 2], 1)]`

Reading the elements one at a time (`for p in outer(...): print(p[1])`) prints
`0` and `1` correctly, so the tuple slot itself is right; the value is lost when
the list is built or printed. The `i == 0` case is the only one that goes wrong,
which points at the zero being taken for a null pointer (a boxed word read as a
null object).

The same program with the tuple yielded at module level and `list(...)` in
`main` behaves the same way, so this is not specific to a nested generator.

## Where to look

- The list-of-tuples repr: `print` of a `MojoList` whose elements are tuple
  pointers. A zero element is treated as `None` (`mojo_box_none()` is the same
  bit pattern as a null word in some paths).
- The producer side: how the tuple slot kind is recorded when the generator's
  values are appended into the list (`mojo_list_append_word` vs the plain
  append). See `mojo/backend_gimple/cpp_core.py`, `_dyn_slots`.

## Exact next step

1. Confirm which side is wrong: print `list(walk(body))[0][1] == 0` and
   `type(list(...)[0][1])`-style checks, and dump the list's element word for
   index 0 (it should be a tagged `0` int box, not a null word).
2. If the producer stores a bare `0` for the int slot while the list read path
   expects a box, make the tuple-to-list append use the same box the direct
   yield uses. Pin with a `test_generator_stdout` case in
   `test_gimple_generator_runner.py` that prints `list(...)` (the repr, not the
   element) and expects `[([1, 2], 0), ([1, 2], 1)]`.

## Second gap seen in the same probe (not yet filed separately)

A nested generator factory returned through two levels of nested defs
(`def outer(body): def inner(fn): ... return walk(fn)` ... `return inner(body)`)
is iterated in `main` as `for p in outer(...)`. The compiled program then fails
to iterate it: `mojo_unsupported_iter: 'for' loop over unsupported iterable type
<unknown>: MojoGenerator *`, and the loop body runs zero times (silent). CPython
prints the elements. Returning `list(walk(fn))` works. Next step: the iterable
type of a call whose result is the return value of a nested def that returns a
generator object should resolve to the generator kind, or be refused honestly
rather than silently iterating zero times.
