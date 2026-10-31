"""`contextlib` — the context manager that does nothing, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name in
a search root and that wins outright, over the host-module list, so this file is
what `import contextlib` binds to. It lives in `formal/hostmods/`, the directory
that resolver adds as its last search root and that no other resolver in the tree
lists — see `_HOSTMODS_ROOT` for why these did NOT go at the repository root,
where the first three of them captured `import os` in the compiler's own sources.

ONE STRUCT, AND IT IS NOT A SHORTCUT
------------------------------------
CPython's `contextlib` is context managers, and a context manager is an OBJECT
with an `__enter__` and an `__exit__`. That is now what this path lowers: a
`with` runs `__enter__` to produce the name the body sees and `__exit__` on the
way out, and it REFUSES a `with` whose value cannot be entered and exited rather
than binding the name to the value and running the body (`formal/build.py`'s
`_rewrite_with_statements`, and `model.struct_is_context_manager` for the rule).
So `nullcontext` below is a struct with those two methods, and the whole of what
this module has to add is the one CPython class whose meaning they carry
completely.

The measurement that decides the rest is unchanged and is still what the
absences below turn on: a formal value is ONE 64-bit word, so a context manager
here has to be a value two methods can be dispatched on, and the only such value
is the frame address of a struct of more than one field
(`model.struct_is_context_manager`). CPython's own `nullcontext` keeps two
attributes — `enter_result` and `exit_result` — so the honest mirror of it is
representable, and this one is.

`test_formal_core_hostmods.py`'s `ctx` group checks `nullcontext` against
CPython's own for all three arities on both backends — and it goes through the
protocol now, so a `nullcontext` that did not answer `enter_result` from
`__enter__` would print the wrong number rather than bind wrongly.
`test_formal_tempfile.py`'s `TemporaryDirectory` group is the standing
measurement for the half that has EFFECTS, because `nullcontext`'s exit does
nothing at all.

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
    naming. `with closing(x) as y:` needs `y` to be `x.close()`'s result while
    the manager holds `x` itself, so it needs TWO words — and this path has one.
    Measured: `with closing(7) as v:` used to build, run the body and print
    `v=7`, and CPython raises `AttributeError: 'int' object has no attribute
    'close'`; now it is refused by the `with` rule above, which is the same
    answer with the reason attached.
  * `ExitStack`, `AsyncExitStack` — a registry of exits applied in REVERSE order
    on the way out. A struct of more than one field could hold that list, but
    `__exit__` would have to APPLY it, and applying a list of calls is a
    generator shape this path does not lower — so the ordering guarantee, which
    is the reason the class exists, has nothing to live in.
  * `chdir` (3.11+) — for the same reason as `closing`: the restore on the way
    out is the entire point, and `__exit__` would have to call `os.chdir` on the
    value the body may also have changed.
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
The 0 is the FIELD's default rather than a substitute computed at the call,
because the constructor is called with no arguments at all from a `with`, and a
module-level name has no storage here besides a class body's own initializers.
"""


struct nullcontext:
    """`contextlib.nullcontext(enter_result=None, exit_result=None)`.

    Two fields because CPython's keeps two, and two because a context manager on
    this path has to be a struct of MORE THAN one field: a one-field struct's
    receiver IS that field, so there is no address to dispatch a method on and no
    second thing to remember. `enter_result` is what `__enter__` hands the body
    and `exit_result` is what `__exit__` answers, which is CPython's own
    arrangement and is why both arities of the constructor are answerable: an
    omitted argument takes the field's own class-level default.
    """
    var enter_result: Int = 0
    var exit_result: Int = 0

    fn __enter__(self) -> Int:
        """`__enter__` returns `enter_result`, which is what the `as` name binds."""
        return self.enter_result

    fn __exit__(self) -> Int:
        """`__exit__` returns `exit_result` — False in CPython, so nothing is suppressed.

        Nothing can be suppressed here in any case: this path has no unwinder,
        so no edge runs from a raise site into anything (`suppress` above).
        """
        return self.exit_result
