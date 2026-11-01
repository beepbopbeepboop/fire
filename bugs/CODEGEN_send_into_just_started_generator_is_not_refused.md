# CODEGEN_send_into_just_started_generator_is_not_refused: `g.send(v)` on a fresh generator runs it instead of raising TypeError

Found 2026-11-01 while fixing CODEGEN_cpp_send_emits_default_path_symbol. It is
NOT cpp-specific: the default stack-switch path does the same.

## Repro

```python
def g():
    yield 1
    yield 2

def main():
    it = g()
    print(it.send(7))
main()
```

CPython: `TypeError: can't send non-None value to a just-started generator`
(the reference program dies with that traceback, exit 1).

Compiled, with `coro.pinned('cpp')` and with `coro.pinned('stackswitch')`
alike: exit 0, stdout `1\n`. The send resumes the body to its first `yield`
and the value is discarded.

## Why

Neither send entry checks whether the generator has started. The cpp
`{base}_send` (cpp_async.py, `{base}_step`) stores the word and resumes; the
stack-switch path calls `__mojo_gen_resume(gen, send)` (emit_calls.py
`_lower_generator_send`). Only a `send(None)` on a fresh generator is legal,
and nothing distinguishes it from `send(7)`.

## Next step

1. Record "started" on each path: the cpp promise gets a `bool started` set
   by `{base}_step` on its first successful resume (or test
   `h.promise()` state before the first resume), and `{base}_send` refuses a
   non-None word while unstarted by raising TypeError through the existing
   `_MojoCppExc` / `mojo_exc_type_set` pattern used for StopIteration.
2. The stack-switch equivalent belongs in `runtime/fire_coro_gen.c`
   (`__mojo_gen_resume`), or in `_lower_generator_send` as a guarded branch.
   Choose one place: the runtime, so the check cannot be bypassed.
3. Pin with a `run_cpp_send_tests`-style case under both pins, expecting the
   TypeError (compare stdout up to the exception; CPython's own run is the
   oracle, so the reference must catch it: `try: it.send(7) except TypeError:
   print("TypeError")`).
