# CODEGEN: an exception object has no `args` (`StopIteration.value` rows FIXED 2026-11-01)

Found 2026-11-01 while working `bugs/hard/CODEGEN_frame_model_for_test_frame.md` (test_frame's `t3`: `c.send(None)` raises
`StopIteration` whose `.value` is the coroutine's result). Three silent or loud divergences, all measured on master with
`python3 fire.py build x.py`:

| program | CPython | compiled |
|---|---|---|
| `raise StopIteration(5)` ... `except StopIteration as ex: print(ex.value)` | `5` | `None` (exit 0) |
| `def g(): yield 1; return 5` ... `next(it); next(it)` in `try/except StopIteration as ex: print(ex.value)` (also `it.send(None)`) | `5` | `None` (exit 0) |
| `async def t3(): return 7` ... `c = t3(); c.send(None)` in `except StopIteration as ex: print(ex.value)` | `7` | `None` (exit 0) |
| `raise ValueError("boom")` ... `except ValueError as e: print(e.args[0])` | `boom` | `AttributeError: args` (exit 1) |

Cause: `except X as e` binds `e` to the raise's message pointer (`mojo_exc_msg_get`/`mojo_exc_obj_set`); there is no exception OBJECT
carrying the constructor arguments. The generator/coroutine exhaustion sites (`emit_calls.py`, three `mojo_exc_type_set(StopIteration); mojo_raise()`
sites in `_lower_generator_next`/`_lower_generator_send`/...) raise with no payload, and `MojoGen.retval` (`fire_coro_gen.c`, filled by
`__mojo_gen_resume` on completion) is never attached to the exception.

Plan:
1. Runtime (`runtime/fire_runtime.[ch]`): `MojoExc { int64_t type; char *msg; MojoList *args; }`; `mojo_exc_new(type, msg, args)`; `mojo_exc_args(obj)`;
   `mojo_raise_obj(type, obj)` setting `mojo_exc_obj_set`. Keep `mojo_exc_msg_get` working for every existing raise (msg stays the string form).
2. `raise Cls(a, b)` lowering (emit_stmts `_gen_stmt_RaiseStmt`): when the class is a builtin exception or a user subclass, build the `MojoExc` with the
   argument list; `except ... as e` binds `e` to the object when the module reads `e.args` / `e.value` / `e.<attr>`, else to the string as today (no change
   to the 99% case, so no churn in generated C).
3. `e.args` -> `mojo_exc_args(e)`; `StopIteration.value` -> `args[0]` or None; `ex.value` for a generator return: at the exhaustion sites attach
   `__mojo_gen_retval(handle)` as `args[0]` (kind-tagged like the generator's value slot).
4. Tests (run-compare against CPython in `test_gimple_runner.py`): the four rows above, plus `str(e)`/`print(e)` unchanged for exceptions raised with
   several args (`raise ValueError("a", 2)` prints `('a', 2)`).
Related: `bugs/hard/CODEGEN_frame_model_for_test_frame.md` (test_frame's `t3` needs row 3).


## Status (2026-11-01): rows 1-3 FIXED, row 4 (`e.args`) open

`StopIteration.value` now works: `mojo_exc_value_set/get` (runtime/fire_runtime.c; cleared by `mojo_exc_type_set`, so a later unrelated raise never
inherits it), `__mojo_gen_stop_value(handle)` (fire_coro_gen.c; attaches a stack-switch generator's / coroutine's return value only when its body made a
valued `return`, tracked by `MojoCoro.ret_set`) called at the three exhaustion sites in `emit_calls.py`, `raise StopIteration(x)` sets it, and `ex.value` on an
`except ... as ex` name reads it (`None` when absent). Test `gimple_stopiteration_value` matches CPython (generator return int/str, bare return, fall-off,
coroutine result via `c.send(None)`, `raise StopIteration(9)`, bare `raise StopIteration`). Gate: generator runner 439 passed with master's 5 failures,
`compile_stdlib.py` 0 unexpected (not gated by `test_selfhost.py`, red on master since 18f122b7c). Not covered: a C++20-coroutine generator (`_mojogen_*`) still answers None.
Open: row 4 and the `MojoExc` object of steps 1-3 above (`e.args`, `str(e)` of a multi-argument exception).
