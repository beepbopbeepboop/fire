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

## Status (2026-11-12) — truthiness fixed; bytes printing split out

**Root cause (found and fixed).** `mojo/backend_gimple/emit_methods.py`, the
`os.path.split` arm, word-argument branch: the result list's elements were
recorded as `int64_t` (`gen._elem_types[t] = 'int64_t'`). A word argument is a
str OR a bytes path, so the parts are words of unknown kind; recording
`int64_t` made the unpacked `dirname` a plain number and `if not dirname:`
lowered to `dirname == 0`. An empty str head is a live non-NULL pointer, so
it read as true. The fix leaves the element kind unrecorded, as the bytes arm
directly above already did; the unpacked locals are then marked dyn-word
(`loops_shared.py`, `_dyn_word_vals`) and the test lowers to
`mojo_truthy_word`, which answers a live str by its first byte and a bytes
object by its length.

**Landed.** `test_os_path_split_word_truthy.py`: the repro generator without
`MOJO_CORO`, built with `fire.py build`. The str cases (`a`, `b.py`, `*.py`)
match CPython, and the bytes cases count yields (`b'*.py'` → 1,
`b'a/b.py'` → 2) instead of printing. Red without the fix (`''` printed,
bytes counts 2/2), green with it. Existing `test_bytes_os_path_regress.py`
(16 cases) and `test_regress_split_coro.py` still pass.

**Still open (this doc is NOT done).** Step 3 of the Next step — the bytes
variant printing `b'*.py'` — is blocked by a separate defect: a generator's
bytes yield reaches the consumer as a raw word that `mojo_repr_boxed` prints
as an address. Filed as `bugs/CODEGEN_coro_a3_generator_bytes_word_print.md`
with the two candidate fixes. Full fix = that doc's quick test restored to
print the bytes lines, then this doc and that doc deleted together.

## Done when

`python3 fire.py build` of the repro above (no `MOJO_CORO`) prints
`a`, `b.py`, `*.py`, `b'*.py'`, `b'a'`, `b'b.py'` — the same lines CPython
prints — which is `test_os_path_split_word_truthy.py` with its bytes cases
restored to `print(n)` (see the bytes doc's Next step 2).
