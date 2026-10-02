"""`contextlib` — the context manager that does nothing, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name in
a search root and that wins outright, over the host-module list, so this file is
what `import contextlib` binds to. It lives in `formal/hostmods/`, the directory
that resolver adds as its last search root and that no other resolver in the tree
lists — see `_HOSTMODS_ROOT` for why these did NOT go at the repository root,
where the first three of them captured `import os` in the compiler's own sources.

ONE FUNCTION, AND IT IS NOT FORGETFULNESS
-----------------------------------------
CPython's `contextlib` is context managers, and a context manager is an OBJECT
with an `__enter__` and an `__exit__`. What this path has instead was measured,
arm64 and x86-64, on the shapes themselves:

    def nullcontext(v): return v
    with nullcontext(11) as x: ...        # x binds to 11 on BOTH backends

`with EXPR as TARGET` evaluates `EXPR`, evaluates the body, and binds `TARGET` to
the expression — there is no dispatch through a dunder to get wrong, so a context
manager whose `__enter__` returns its argument is *already* what the keyword
statement means, with nothing left for this module to add. That is the whole of
`nullcontext`: it hands back the value the caller passed and does nothing on the
way in or out.

So this module is one function because that is the one name in CPython's
`contextlib` whose meaning is fully carried by that shape. The measurement that
separates it from its neighbours is what each of them needs BEYOND the binding,
and it is in "WHAT IS NOT HERE" below.

`test_formal_contextlib.py` checks `nullcontext` against CPython's own for both
arities — `nullcontext(v)` and `nullcontext()` — on both backends, and pins each
absence below as a refusal naming itself.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `suppress` — an EXCEPTION is a raise, and this path has no raise
    (`FORMAL.md` phase 7). Its whole meaning is "swallow the exception the body
    raises", so with no exceptions a `suppress` would suppress nothing and would
    look like it worked: the body runs, nothing is caught, and the difference is
    only visible in the program that was supposed to fail. That is a silent wrong
    answer wearing a working-looking name.
  * `redirect_stdout`, `redirect_stderr` — a STREAM. `formal/hostmods/sys.mojo`
    already says what is missing (`sys.stdout` has no source here at all, so the
    caller supplies the vector), and `formal/hostmods/io.mojo` says the same one
    level up. A redirect that did not redirect would capture nothing and the
    caller would read an empty buffer as "the program printed nothing".
  * `contextmanager` — a DECORATOR over a generator function. Both halves are
    refused here: a decorator on a function OR a class is silently DROPPED by
    both backends (`bugs/COMPILE_FAIL_decorator_application_dropped.md`), so
    `@contextmanager` would build and turn the generator function into an ordinary
    one that returns a generator nobody consumes.
  * `closing` — LOOKED LIKE `nullcontext` AND IS NOT, which is why it is worth
    naming. `with closing(x) as y:` binds `y` to `x` on this path, exactly as
    `nullcontext` does, so it builds and answers the binding correctly — and then
    silently never calls `x.close()`. Measured: `with closing(7) as v:` builds,
    runs the body and prints `v=7`; CPython raises
    `AttributeError: 'int' object has no attribute 'close'`. For a real closable
    the divergence is worse and quieter: the resource is never released and the
    program prints its results as if it had been. A name that answers the easy half
    of its contract and drops the half that matters is the one thing a mirror of
    CPython must not export, so it is absent rather than approximately right.
  * `ExitStack`, `AsyncExitStack` — a registry of exits applied in REVERSE order
    on the way out. There is no `__exit__` to apply them in, so the whole ordering
    guarantee — the reason the class exists — has nothing to live in.
  * `chdir` (3.11+) — for the same reason as `closing`: the restore on the way out
    is the entire point and there is no way out to do it on.
  * `AbstractContextManager`, `ContextDecorator`, `aclosing` — TYPES and
    decorators; `formal/hostmods/typing.mojo` says the same about `Optional`, and
    the decorator measurement is above.

THE ONE THING THAT IS NOT QUITE CPYTHON, STATED HERE RATHER THAN LEFT
--------------------------------------------------------------------
`nullcontext()` with NO argument binds `None` in CPython and **0** here. That is
this path's representation of `None` and not an approximation of it: `None` folds
to the word 0 (`model.NONE_WORD`), which is the only thing a one-word value can
say. The fold is lossy in exactly one direction — after it, `x == 0` and
`x is None` are the same expression — and that one case is refused by name rather
than answered (`formal/build.py`'s `refuse_none_comparisons`). So a program can
distinguish them, and a program that merely passes the value along is unaffected.
The 0 is the DEFAULT argument's value rather than a substitute computed at the
call, because a module-level name has no storage here and a default is the same
spelling `os` and `struct` use for the same reason.
"""


def nullcontext(v = 0) -> int:
    """`contextlib.nullcontext(enter_result=None)`: a manager yielding `v`.

    `with nullcontext(v) as x:` binds `x` to `v` and does nothing else, which is
    what CPython's does — its `__enter__` returns `enter_result` and its
    `__exit__` returns False (so the body may suppress nothing and nothing is
    suppressed). Checked against CPython's own for both arities by
    `test_formal_contextlib.py`.

    The default is 0 rather than a spelling of `None` because `None` is the word
    0 on this path (`model.NONE_WORD`); the docstring above states the one
    construct that can tell the difference and where it is refused.
    """
    return v
