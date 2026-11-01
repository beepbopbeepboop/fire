# CODEGEN_cpp_send_emits_default_path_symbol: `gen.send(v)` on the cpp generator path emits the default path's runtime call

## Status (2026-11-01, found while landing the cpp lowering of `x = yield`)

Under the cpp escape hatch (`coro.pinned('cpp')`, `MOJO_CORO=cpp`), a call
`it.send(v)` on a generator is not lowered by the cpp emitter at all. The
call reaches the generated C as the default (A3 stack-switch) path's runtime
entry point `__mojo_gen_resume`, which the cpp translation unit never
declares, so the program fails to build:

```
prog.c: In function '_gimple_main':
prog.c:8:10: error: implicit declaration of function '__mojo_gen_resume'
```

It is a loud build failure, not a silent wrong value. It is still a bug: a
program that is valid Python cannot be built on the cpp path.

### Repro

```python
def g():
    yield 1
    yield 2

def main():
    it = g()
    print(next(it))
    print(it.send(7))
main()
```

Run with `coro.pinned('cpp')` (a driver: `test_gimple_generator_runner._build_generator_program`
inside that block). CPython prints `1` then `2`.

The generator here yields statement-only, so the failure is the `send` call
itself, not the generator. (Verified on this tree. A generator whose body
also has `x = yield` was not run through `send`.)

### Why the cpp protocol has no send today

Every cpp consumer resumes a generator through `{base}_resume(handle)` with no
value argument: `next(g)`, a for loop, `yield from`, and the nested-generator
drivers. The promise's `yield_value` returns `std::suspend_always`, whose
`await_resume` is `void`. So `x = yield` on this path binds the None box
(`mojo_box_none()`, see `_cpp_assign_received_yield` in
`mojo/backend_gimple/cpp_core.py`), which is the value every existing consumer
delivers. That is faithful only while nothing sends a value.

### Next step

1. Give the resume a sent word. Two shapes were weighed:
   - a `sent` word in the promise. Do this with care: the cpp backend's own
     comment in `mojo/backend_gimple/cpp_async.py` (`_gen_cpp_generator_unit`,
     the `unhandled_exception` note) records a GCC 15 coroutine-frame-layout
     miscalculation triggered by an extra promise field on a coroutine taking
     2+ parameters. Test a multi-parameter generator with a sent field before
     relying on it.
   - the resume entry point takes the word (`{base}_resume(g, word)`), which
     changes every consumer listed above and the signature registry
     (`mojo_gen_sig_register` in `cpp_async.py`).
2. Lower `it.send(v)` on the cpp path to resume with `v` and return the next
   yielded value, the same contract `__mojo_gen_resume(gen, send)` gives the
   default path.
3. Make `x = yield` read the sent word instead of `mojo_box_none()`
   (`_cpp_assign_received_yield`). That helper's docstring marks the one place.
4. Pin with `test_generator_matches_cpython` under `coro.pinned('cpp')`:
   `send` into an `int` yield, a `str` yield, and a `None` send.

Until (2) lands, `send` on the cpp path should be refused at codegen with
`_UnsupportedGeneratorShape`, not left to surface as a gcc error. That refusal
is the smallest honest step and can land on its own.
