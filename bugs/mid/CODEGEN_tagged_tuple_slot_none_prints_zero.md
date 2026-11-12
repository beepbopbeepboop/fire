# CODEGEN_tagged_tuple_slot_none_prints_zero: a None in a tuple yield reads back as 0

Class: **mid** (this doc lives in `bugs/mid/`).

## Symptom

A generator that yields tuples, where one slot is `None` on some yields, reads back
the `None` slot as `0`, and `== None` is false. The unpacked name is a tagged word,
but the producer stored `0` with an integer slot kind, so there is no box to read.

Reproducer (CPython oracle, measured 2026-11-11):

```
def g():
    yield 1, 10
    yield None, 20
    yield 2, 30
def main():
    for a, b in g():
        print(a)
        print(a == None)
        print(b + 1)
main()
```

CPython: `1 False 11 None True 21 2 False 31`.
Compiled (HEAD 73076be07 plus the tuple-slot tagging change in this round):
`1 False 11 0 False 21 2 False 31`.

The `b + 1` part is fixed by this round (the tuple slot is tagged, so the
arithmetic reads it by kind). The `a` part is not: the list the generator builds
records slot 0 as an integer, so `mojo_list_get_boxed` returns the bare `0`.

## Where the producer is

The generator body is compiled as a C++ coroutine unit (`__mojo_gen_*`,
`__mgco_*`); its tuple yields are built by `mojo/backend_gimple/cpp_core.py` around
line 6300 (`_dyn_slots`, which switches to the kind-recording appends:
`mojo_list_append_word(t, mojo_box_none())` for a `None` element). That branch is
supposed to fire for `yield None, 20`, because `_is_none` is true for a `None`
element. It did not produce a kind-`'n'` slot in the measured run, so either the
branch is not reached for this shape, or the element is typed before the check.

Not yet established: which of those two it is. The C++ unit is not in the gimple
dump (`compile_to_gimple` does not print it), so the next step is to dump the unit
the C++ path writes (its path is in the build's temp directory) and read the append
for slot 0.

## Fix plan

1. Dump the C++ coroutine unit for the reproducer and read the append for slot 0.
2. If `_dyn_slots` is not set for `None`: fix the `_is_none` test in
   `cpp_core.py` so a `None` element always marks the tuple dynamic.
3. If the branch runs and emits `mojo_box_none()`: the bug is in the consumer
   (`mojo_list_get_boxed` on a slot the append recorded as 'n'); check that
   `mojo_list_slot_kind` reports `'n'` for that slot.
4. Regression: the reproducer above, as a CPython-oracle case in
   `test_gimple_generator_runner.py`'s `run_tagged_for_target_bind_tests`.

## Status

Not started past the reproducer. The tuple-slot tagging change (`emit_loops.py`,
`_emit_generator_tuple_unpack`) is in place and fixes `b + 1`.
