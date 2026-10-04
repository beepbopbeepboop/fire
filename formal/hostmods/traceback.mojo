"""traceback.mojo — CPython's `traceback`, for a target that has no unwinder.

`formal/imports.py` resolves an import in four passes and the FIRST is "a Mojo
source `<name>.mojo` in a search root WINS OUTRIGHT, even over the host-module
list". This file is that source for the name `traceback`, so `import traceback`
is no longer the refusal

    imports 'traceback', which is a host module (CPython standard library),
    which has no Mojo source for this backend to compile

It lives in `formal/hostmods/` — the last search root, and the only one no other
resolver in this tree lists. See `_HOSTMODS_ROOT`.

WHY IT IS TWO FUNCTIONS, AND WHY THEY ARE NOT APPROXIMATIONS
------------------------------------------------------------
CPython's `traceback` formats and prints the traceback of the exception being
handled. This backend has no `raise`, no exception object and no unwinder
(`FORMAL.md` phase 7; a handler arm with a body is refused by name, so not one
statement inside an `except` ever reaches the program that runs). **So there is
never an exception in flight, and the state `traceback` reports on is not a
degenerate case of the real one — it is the only state this target can be in.**

That matters because CPython answers that state itself, and its answer is not
"nothing":

    $ python3 -c 'import traceback; print(repr(traceback.format_exc()))'
    'NoneType: None\\n'

`sys.exc_info()` is `(None, None, None)` with nothing being handled, and
`format_exception_only(None, None)` spells that as the type name of `None`, a
colon, the repr of `None` and a newline. So `format_exc()` here returns that
exact string and `print_exc()` writes that exact string to descriptor 2 — which
is byte-for-byte what CPython does in the state this target is always in, and
which `test_formal_traceback.py` measures by asking CPython rather than by
asserting a constant.

A `print_exc()` that wrote NOTHING would have been the obvious cheaper answer
and would have been WRONG on this host: CPython writes four lines' worth of
`NoneType: None` for every call that finds no exception, so a mirror that
silently wrote nothing would disagree with the host on all 30 of this
repository's call sites the first time anybody looked at stderr.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `format_exception`, `print_exception`, `format_exception_only` — all three
    take an EXCEPTION OBJECT as a required positional argument in CPython 3.14
    (measured: `traceback.format_exception()` raises `TypeError: format_
    exception() missing 1 required positional argument: 'exc'`), and there is
    no such object on this target to pass. A zero-argument version of either
    would answer a question CPython does not accept the question for.
  * `format_stack`, `print_stack` — the CURRENT stack, which this target does
    have; the answer does not fit. Each line is the frame's file, its line
    number, its function name and its text joined into one string, and
    composing a string out of parts is refused on this path
    (`bugs/FORMAL_string_composition_has_no_buffer.md` — the row the 2026-10-04
    sweep measured at 115 files). A stack printer that printed a fixed string
    would be a plausible wrong answer about the program it claimed to describe.
  * `print_tb`, `format_tb`, `extract_tb`, `walk_tb`, `clear_frames` — take or
    answer a traceback OBJECT. Same missing thing as above, and
    `clear_frames(tb)` is the sharpest of them: its entire meaning is mutating
    a traceback the caller holds, and a value on this path is one 64-bit word
    with no storage for the frames.
  * `TracebackException`, `FrameSummary`, `StackSummary` — three record types
    over exactly those frames. `namedtuple` cannot be built at run time either
    (there is no word that denotes a type,
    `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`).
  * `print_exception_only` — does not exist in CPython 3.14; it was removed in
    3.13. Naming it here would be advertising a name the host does not have.

THE TWO THINGS THAT ARE NOT QUITE CPYTHON, STATED HERE
------------------------------------------------------
  * `print_exc()` returns 0 where CPython returns `None`. `None` folds to the
    word 0 on this path (`formal/model.py`, `NONE_WORD`), which is the only
    thing a one-word value can say; `formal/hostmods/contextlib.mojo` states
    the same about `nullcontext()` and this is that fold, not a substitute
    computed at the call.
  * `print_exc()` takes NO arguments, where CPython's is
    `print_exc(limit=None, file=None, chain=True)`. Two of the three are
    about output STREAMS (`formal/hostmods/io.mojo` says what is missing, and
    it is the same missing thing `sys.stdout` is) and one bounds a frame list
    that cannot exist. Every call site in this repository spells it bare —
    30 of them, measured — so the shape that is reachable is the shape that is
    exported; the arguments it drops are named here rather than accepted and
    ignored, because a function that took a `limit` and answered as though it
    had not been given one is the silent-wrong-answer shape
    `formal/hostmods/contextlib.mojo` declines to ship for `closing`.
"""


from sys import write_stderr


# What CPython's `format_exc` produces when `sys.exc_info()` is `(None, None,
# None)`, which is the state this target is always in.  A module-level LITERAL,
# so it is folded into the manifest and substituted at each use site
# (`formal/build.py::_publish_imported_constants`) as well as readable inside
# this module — it is both the answer and the text `print_exc` writes.
NO_EXCEPTION_IN_FLIGHT = "NoneType: None\n"


def format_exc() -> str:
    """`traceback.format_exc()`: the traceback of the exception being handled.

    There is none being handled, so this is CPython's own answer for that state
    and not a placeholder for one: `'NoneType: None\\n'`, the text
    `format_exception_only(None, None)` produces.  Measured against CPython by
    `test_formal_traceback.py`, on both backends.
    """
    return NO_EXCEPTION_IN_FLIGHT


def print_exc() -> int:
    """`traceback.print_exc()`: write that same text to descriptor 2.

    Descriptor 2 unbuffered, which is what `sys.write_stderr` is and what
    CPython's `sys.stderr` is here — `formal/hostmods/sys.mojo` owns that
    write and this module calls it rather than opening a second path to fd 2,
    so there is one reader of descriptor 2 in this tree.

    Returns 0, which is `None`: see the module docstring.
    """
    write_stderr(NO_EXCEPTION_IN_FLIGHT)
    return 0
