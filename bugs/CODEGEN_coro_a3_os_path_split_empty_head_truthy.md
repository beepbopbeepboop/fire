# CODEGEN (A3 default coroutine path): `if not head` after `head, tail = os.path.split(p)` is wrong for an empty head

Found 2026-11-02 while fixing the C++ emitter's `os.path.split` lowering (the
`0.split(p)` / unpacked-to-zero bug; the `MOJO_CORO=cpp` path is fixed, see
`test_coro_cpp_os_path_split.py`). This doc is about the DEFAULT A3 path.

## Repro (measured)

    import os

    def g_split(pathname):
        dirname, basename = os.path.split(pathname)
        if not dirname:
            yield basename
            return
        yield dirname
        yield basename

    def main():
        for n in g_split('a/b.py'):
            print(n)
        for n in g_split('*.py'):
            print(n)

Run as `python3 fire.py --jit <file>` (default coroutine path, no MOJO_CORO):

    a
    b.py
    <empty line>
    *.py

CPython and the `MOJO_CORO=cpp` path both print `a`, `b.py`, `*.py`.

## What is wrong

For `'*.py'` the head is `''`, so `not dirname` must be true and only `*.py` is
yielded. The A3 path yields `''` and then `*.py`, i.e. it takes the
`not dirname` branch as false: the empty str head is read as truthy.

## Where to look

- `mojo/middle/coro.py` ~lines 395-434 and 597-602: `os.path.split` results are
  typed as str-kinded (`char *`) for a str argument, and unpacked elements are
  bound from that pair. The truth test of such a local should be a length test
  (`mojo_strlen(...) == 0`), not a non-NULL test.
- The `not <name>` lowering for a str-kinded local in the A3 emitter (the
  generator body path that `gimple_gen_coro.py` / `coro_emit.py` drives).

## Next step

1. Dump the A3 C for the repro (the coroutine unit) and find the `not dirname`
   expression. Confirm whether it is a pointer test or a `mojo_truthy_word` on a
   word whose kind was lost.
2. Fix the truth test for the split-unpacked element so an empty head is falsy.
   Pin it with a test next to `test_coro_cpp_os_path_split.py`, with the same
   expected output (`a`, `b.py`, `*.py`) but run WITHOUT `MOJO_CORO=cpp`.
3. Check the bytes variant (`b'*.py'`), which must print `b'*.py'` only.
