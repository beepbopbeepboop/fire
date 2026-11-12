# CODEGEN: a `@contextlib.contextmanager` generator is refused by the compiled path

Found 2026-11-12 while compiling the compiler's own `mojo/middle/coro.py` (the probe in
`test_selfhost.py::coro_module_compiles_to_c`).

## What I ran

    compile_module_to_c(open("mojo/middle/coro.py").read(), path, "coro", linkable=False)

## What I saw

    RuntimeError: cannot compile module: function(s) pinned (generator function(s), contain a `yield`) ...

`pinned` was a `@contextlib.contextmanager` generator (`mojo/middle/coro.py`, from 48713c415).

## What I expected

A `@contextmanager` generator used only through `with pinned(...)` compiles, or at least
its refusal is not the whole module's refusal.

## Status

Worked around, not fixed: `coro.py`'s `pinned` is now a plain class with `__enter__`/`__exit__`
(same enter/restore semantics), which compiles. The compiled path still refuses any user
`@contextmanager` generator, so user code with one fails to compile.

## Next step

Teach the generator lowering (`mojo/backend_gimple/cpp_async.py` / `module_gen.py`, owned by the
generator lane) to accept a `@contextlib.contextmanager` whose body is a single
`try: yield ... finally: ...`, OR state in the compiled path that it is unsupported. Test:
`test_selfhost.py::coro_module_compiles_to_c` keeps its shape; add a user-code case.
