# CODEGEN_a_none_sent_into_a_generator_prints_zero: `x = yield` resumed with None prints 0

## Status (2026-11-01, found while closing the "a None yield value prints 0" family, 2026-11-01; not fixed)

The value a generator receives at `x = yield` is an int64 slot in the
resume ABI, and it has no None kind. A resume with None (`next(it)`, which
sends None, or `it.send(None)`) therefore hands the generator the raw `0`,
and `print(x)` prints `0` where CPython prints `None`. This is the RECEIVE
side of the None-value family: the yield side (`yield` / `yield None` as an
OUTPUT) is fixed on the default path for every consumer that compiles.

### Repro (default path, measured 2026-11-01)

```python
def g():
    x = yield
    print(x)
    yield 1

def main():
    it = g()
    next(it)     # runs to the bare yield
    next(it)     # resumes with None: x is None, print(x) must print None
main()
```

- CPython: `None`, then nothing further (the generator yields 1 and is not printed again).
- Compiled, default stack-switch path: `0`. Exit 0, silent wrong value.

The explicit-yield variant (`x = yield 7`, then `print(it.send(None))` after a
`next`) gives `0` / `1` where CPython gives `None` / `1`.

Both measured with `test_gimple_generator_runner._build_generator_program` and
`_cpython_stdout` on the same text. The `MOJO_CORO=cpp` probe did not build
(the generator was refused with the straight-line-codegen message), so the cpp
path is UNMEASURED for this shape; do not assume it matches the default path.

### Why it is not a one-site fix

The sent value goes through the same int64 value slot as an ordinary yielded
integer, so a None sent in is indistinguishable from `send(0)` on the wire.
Fixing it needs the resume side to carry a kind: either a tagged resume word
(`mojo_box_none` on the send, unwrapped at the `x = yield` bind, the same
mechanism the yield side uses in `_cpp_tag_yield_sites`) or a second channel.
The bind-site rule in `emit_stmts.py` (the simple-name bind that already keeps
a box for tagged for-targets) is the natural place for the unwrap.

### Next step

1. Pin first, fail-before: add `none_sent_into_generator_default` to
   `run_none_yield_tests` in `test_gimple_generator_runner.py` with the repro
   above, `test_generator_matches_cpython`, expecting `None\n`. Measure it FAILS
   (`0`) before any source change.
2. Decide the resume ABI: resume-with-None as a box (preferred; it reuses the
   yield-side box and the bind-site unwrap) versus a sent-kind flag beside the
   int64 slot. Probe whether `send(v)` for a valued `v` already round-trips
   through `g.send` (the existing `generator_send_*` pins at ~line 6747 do) so
   the change does not move valued sends.
3. Measure the cpp path for the same shape with the correct coroutine env
   (the probe above was refused, so first find which env selects the cpp path
   for a test program) before deciding whether it needs a cpp-side tag too.
4. Gate note for the integrator: a change at the resume/bind path touches every
   `x = yield` in the stdlib. Compare `compile_stdlib.py` `U`/`skip` before and
   after, and `gimplegenerators` in full.
