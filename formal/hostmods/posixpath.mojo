"""`posixpath` — CPython's own spelling of `os.path`, for the formal backend.

**THE MODEL IS ALREADY WRITTEN. This file is a SPELLING, not an
implementation.** `formal/hostmods/os/path/__init__.mojo` IS CPython's
`posixpath` — its own header says the pure-string half is "CPython's
`posixpath`/`genericpath` algorithm for a POSIX target, transcribed" — and
`test_formal_os.py` checks 436 path answers against CPython's own `posixpath`
on both backends. What a file that writes `import posixpath` got instead was a
module-RESOLUTION failure, because `formal/imports.py`'s `resolve_module_path`
looks for a source NAMED `posixpath` and there was none.

So every function below FORWARDS to `os.path` and none of them is a second
implementation. That is said first because a reader who finds thirty `def`s
that all `return` something else should know immediately that there is nothing
behind them.
`bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md` §5 item 3 ranks
this as the third-cheapest thing left in the sweep's 241-file host-import row
and says the same: the fix is "a `formal/hostmods/posixpath.mojo` that
re-exports `os.path`, which is what `os/__init__.mojo` already does for its own
five names".

WHY A `.mojo` FILE AND NOT AN ALIAS IN THE RESOLVER
---------------------------------------------------
`formal/imports.py` could answer `posixpath` with `os/path/__init__.mojo`'s
path, and that would be one line instead of this file. It is not done, for a
reason about what the two spellings then MEAN:

  * `os.path` is reached as `from os.path import join` — a NAME inside a
    package. `posixpath` is reached as `import posixpath`, and CPython's own
    `posixpath` is a MODULE, not a name in `os`. Answering the name `posixpath`
    with that path would make `import posixpath` mean "the `os` package's `path`
    submodule", which is the same source today and stops being the same the
    moment either module gains a name the other did not. A module that IS the
    thing is one indirection a reader can follow; an alias in a four-pass
    resolver is a rule somebody has to know.
  * A `.mojo` file under `formal/hostmods/` is found by PASS 1 of
    `resolve_module_path` ("MOJO SOURCE, any search root"), which wins outright
    over the host-module list. That is the mechanism every other hostmod in this
    tree uses, and using it here too keeps `posixpath` on the same footing as
    `os` rather than on a private exception.

WHY EVERY FORWARD IS A `def`, AND WHY THE CALL INSIDE IS `os.path.f(…)`
------------------------------------------------------------------------
Both halves of that are MEASURED on this tree, and together they are the whole
reason this file is thirty functions rather than six import lines.

**A re-imported name is not in the export table.** The table comes from
`reflect.collect_exports_src`, which publishes the public functions a module
DEFINES. A module of bare `from os.path import dirname` re-exports builds and
links, and then a QUALIFIED call through it has no symbol to bind:

    # posixpath.mojo = `from os.path import dirname` and nothing else
    import posixpath
    posixpath.dirname("/a/b/c")
      -> build: `posixpath` is a linked module but it exports no `dirname`, so
         the call has no symbol to bind. What it does export: …

and it is NOT specific to this module — the same sentence is what CPython's own
`os` re-export gets, on the same tree, for the names it forwards out of
`os.path`:

    import os
    os.isfile("fire.py")          -> the same refusal, naming `isfile`

while `from os import isfile` WORKS, because that spelling binds the name in the
IMPORTER rather than asking the exporter for it. So the difference is the export
rule, not a bug to route around, and the fix that keeps BOTH spellings working
is a real `def` per name. `doc/ABI.md`'s export rule is what that refusal
quotes and `bugs/FORMAL_known_limits.md` §1.1 is where the rule is measured.

**The call inside a forward is spelled `os.path.f(…)`, not a bare `f(…)` and
not an aliased import.** Both alternatives were built and run:

    from os.path import dirname
    def dirname(p) -> str: return dirname(p)     # exit 2, unbounded recursion
    from os.path import dirname as pd
    def dirname(p) -> str: return pd(p)          # dyld: Symbol not found: _pd
    import os.path
    def dirname(p) -> str: return os.path.dirname(p)     # works

The first shadows the import with itself, so the body calls itself; the second
binds a symbol the body cannot find at load. The third is the one that works and
is what every forward below uses, which is also why this file imports `os.path`
and `os` as MODULES and never names a bare `dirname` of its own.

WHAT IS HERE, AND WHY THESE NAMES
---------------------------------
CPython's `posixpath` exports 30 non-underscore names. What is forwarded is
every one of them that `formal/hostmods/os/path/__init__.mojo` answers, plus
the path constants, which are FUNCTIONS on this path because a module-level name
has no storage across a dylib boundary (`formal/hostmods/os/__init__.mojo` gives
this at length: `sep()` and not `sep`).

Measured on this tree, the one file that wants this spelling is
`test_formal_os.py`, and it spells thirteen distinct names. That same file
spells `os.path` everywhere else, which is why the ranked doc calls this thin
evidence and puts it at item 3 rather than item 1. The thinness is real and is
not argued away: what this buys is that a file which writes CPython's spelling
builds, not that any file gets shorter.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `splitroot` — CPython's 3.12 root/final-part/drive splitter, and a
    three-element TUPLE. A tuple on this path is a frame blob whose first word
    is a COUNT: `os/path/__init__.mojo`'s own header says four of its functions
    "carry no return annotation, and it is not an oversight" for exactly that
    reason. Answering it as a two-element tuple would be a plausible wrong
    answer about the drive part. `splitroot_root` below is the ONE piece that is
    one word, and it is that because on a POSIX target the root is `""`, `"/"`
    or `"//"` — see its own docstring, and note that it is a forward rather
    than an implementation, because `os.path` owns that rule now.
  * `commonpath`, `ismount`, `normcase`, `expandvars`, `isdevdrive`,
    `isjunction`, `sameopenfile`, `samestat`, `getatime`, `getctime`,
    `getmtime` — CPython has these and `os/path/__init__.mojo` here does not,
    and this file does not invent an algorithm it exists to forward.
    `normcase` is the IDENTITY on a POSIX target (`fnmatch.mojo` relies on that
    and `test_formal_os.py` checks `fnmatch` against CPython's own `normcase`
    for it), so forwarding it would be a function that returns its argument and
    teaches a caller nothing. `commonpath` takes a LIST, `ismount` needs the
    parent device, `expandvars` needs `environ`, and the three `get*time` names
    are `os.stat` field reads this tree reaches through
    `formal/hostmods/os/_syscalls.mojo`'s `fs_stat_field64`. Each is a name to
    add when a caller wants it, and adding it means writing it in
    `os/path/__init__.mojo` where the algorithm belongs — NOT here, because a
    forward that is also an implementation is the duplication this file exists
    to avoid.
  * The `genericpath` submodule and the `os`/`sys`/`stat` module attributes
    CPython's `posixpath` carries. They are the import cycle CPython has and
    this module does not need.
  * `ALLOW_MISSING`, `defpath`, `altsep`, and the constants as CONSTANTS: the
    six that name a path character are here as functions (`sep()`, `curdir()`,
    `pardir()`, `extsep()`, `pathsep()`, `devnull()`), which is this path's
    spelling. `altsep` is `None` on POSIX and `None` is the word 0, so an
    `altsep()` answering 0 would be a function whose answer is
    indistinguishable from every other 0 on this path — worse than an absent
    name, and `formal/build.py`'s `refuse_none_comparisons` is the check that
    says so.

ONE THING MEASURED, because it is the whole forwarding risk
------------------------------------------------------------
The four tuple-returning functions are the ones a forward could plausibly break,
since a tuple is a frame blob rather than a value. Measured on this tree, arm64,
`split` forwarded through this module and destructured at the call site:

    p0, p1 = posixpath.split("/a/b.c")     ->  /a/b | b.c

which is CPython's answer. What does NOT survive is asking the tuple for its
LENGTH — `strlen(posixpath.split(p))` answers 1 where CPython answers 2 — and
that is not this module's doing: the same is true of `os.path.split(p)` called
directly, measured the same way, because the tuple's count word lives in the
frame of the function that built it. So a caller destructures, which is what
`test_formal_os.py` already does (`emit_case`'s `p0, p1 = {call}`), and a caller
that asks a tuple how long it is was already getting 1 from `os.path`.
"""

import os
import os.path


# ── the pure-string forwards ────────────────────────────────────────────────
#
# One line each, and the docstring on each names CPython's own and points at
# `formal/hostmods/os/path/__init__.mojo`, so a reader who wants the ALGORITHM
# reads that file and not this one.

def join(a, b) -> str:
    """`posixpath.join(a, b)`. CPython's, in `os.path.join`.

    `*parts` is refused on this path, so CPython's variadic one is
    `join(a, b)`, `join3(a, b, c)` and `join_all(parts)` here — which is
    `os.path`'s own spelling and is not invented by this file.
    """
    return os.path.join(a, b)


def join3(a, b, c) -> str:
    """`posixpath.join(a, b, c)`. CPython's, in `os.path.join3`."""
    return os.path.join3(a, b, c)


def join_all(parts) -> str:
    """`posixpath.join(parts)` over a whole list. CPython's, in
    `os.path.join_all`."""
    return os.path.join_all(parts)


def split(p):
    """`posixpath.split(p)`: `(head, tail)`. CPython's, in `os.path.split`.

    NO return annotation, and that is the convention rather than an oversight: a
    tuple is a frame blob, so an annotation here would be a claim in the dylib
    manifest that nothing can keep
    (`bugs/FORMAL_string_equality_of_two_unclassified_words.md`).
    """
    return os.path.split(p)


def dirname(p) -> str:
    """`posixpath.dirname(p)`. CPython's, in `os.path.dirname`."""
    return os.path.dirname(p)


def basename(p) -> str:
    """`posixpath.basename(p)`. CPython's, in `os.path.basename`."""
    return os.path.basename(p)


def normpath(p) -> str:
    """`posixpath.normpath(p)`. CPython's, in `os.path.normpath`."""
    return os.path.normpath(p)


def isabs(p) -> int:
    """`posixpath.isabs(p)`: 1 or 0. CPython's, in `os.path.isabs`."""
    return os.path.isabs(p)


def commonprefix(a, b) -> str:
    """`posixpath.commonprefix(a, b)` over TWO strings. CPython's, in
    `os.path.commonprefix`.

    CPython's takes a LIST and takes that list's minimum and maximum;
    `os.path`'s takes two strings and compares them character-wise, which is the
    same computation with the list flattened. So this is a two-argument
    `posixpath` and `test_formal_os.py`'s `commonprefix2` is CPython's own body
    transcribed over the two-string form — corpus and definition written from
    one source, not two that can drift.
    """
    return os.path.commonprefix(a, b)


def abspath(p) -> str:
    """`posixpath.abspath(p)`. CPython's, in `os.path.abspath`."""
    return os.path.abspath(p)


def realpath(p) -> str:
    """`posixpath.realpath(p)`. CPython's, in `os.path.realpath`."""
    return os.path.realpath(p)


def relpath(path, start) -> str:
    """`posixpath.relpath(path, start)`. CPython's, in `os.path.relpath`.

    `start` is REQUIRED and not defaulted: a call from another image does not
    materialize a callee's default arguments — the caller has no signature to
    read them from — so a defaulted parameter arrives as a stack address
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). CPython
    defaults `start` to `os.curdir`, so a caller here passes `curdir()`.
    """
    return os.path.relpath(path, start)


def expanduser(p) -> str:
    """`posixpath.expanduser(p)`. CPython's, in `os.path.expanduser`."""
    return os.path.expanduser(p)


def splitdrive(p):
    """`posixpath.splitdrive(p)`: `(drive, tail)`. CPython's, in
    `os.path.splitdrive`. Always `("", p)` on this target, which is why the
    tuple's second element is the whole answer and not a tail computed here."""
    return os.path.splitdrive(p)


def splitext(p):
    """`posixpath.splitext(p)`: `(root, ext)`. CPython's, in
    `os.path.splitext`."""
    return os.path.splitext(p)


def splitroot_root(p) -> str:
    """`posixpath.splitroot(p)[1]`: the ROOT, as ONE WORD.

    `splitroot` itself is absent (module docstring), and this is the piece of it
    that is a single word. CPython's answer is `(drive, root, tail)`; on a POSIX
    target the DRIVE is always `""`, so the whole of what is left is the root
    and it is a string of slashes.

    **The index is `[1]` and not `[0]`**, and that is worth one line because
    getting it wrong is the obvious mistake here and it fails SILENTLY: element
    0 is the drive, which on this target is the empty string for every input,
    so a `splitroot(p)[0]` would answer `""` for an absolute path and look right
    for a relative one.

        posixpath.splitroot("/a/b")   ->  ('', '/',  'a/b')
        posixpath.splitroot("//a/b")  ->  ('', '//', 'a/b')

    **AND THE ROOT IS NOT `isabs(p)`, which was the first version of this
    function and was wrong on `//`.** POSIX reserves a path that begins with
    EXACTLY TWO slashes for implementation-defined meaning, and CPython honours
    it by making the root `//` for those paths and `/` for three or more:

        posixpath.splitroot("//a/b")[1]  ==  '//'
        posixpath.splitroot("///a")[1]   ==  '/'
        posixpath.splitroot("/a/b")[1]   ==  '/'
        posixpath.splitroot("a/b")[1]    ==  ''

    So the rule is three tests in this order: not starting with `/` at all gives
    `""`; starting with `//` and NOT a third `/` gives `"//"`; and starting
    with `/` gives `"/"`. `isabs` collapses the last two and answers `/` for
    `//a/b`, which `test_formal_posixpath.py`'s `forward` group caught against
    CPython over the `//` case and `//a`-style corpus entries.

    Named with the `_root` suffix rather than as `splitroot` precisely so it
    cannot be mistaken for the tuple it is one third of: a caller that wants
    CPython's `splitroot` is refused, which is the honest outcome rather than a
    two-element answer that silently drops the drive part.

    **THE RULE LIVES IN `os.path`, HERE, SINCE 2026-10-03.** This used to carry
    its own copy of the three tests — the two `if` chains over `p`, `p + 1` and
    `p + 2` — and there is now one of them,
    `os/path/__init__.mojo`'s `splitroot_root`, because the same question has
    three consumers and two of them are in `os.path`: `normpath` asks it to
    decide how many leading separators to write back, and `realpath` asks it to
    decide whether to collapse CPython's POSIX `//` root. A second copy here
    would be three answers to one question, and `posixpath`'s answer would be
    the one no other function could see.
    """
    return os.path.splitroot_root(p)


# ── the four predicates CPython re-exports from `genericpath` ───────────────

def exists(p) -> int:
    """`posixpath.exists(p)`: 1 or 0. CPython's, in `os.path.exists`."""
    return os.path.exists(p)


def isfile(p) -> int:
    """`posixpath.isfile(p)`: 1 or 0. CPython's, in `os.path.isfile`."""
    return os.path.isfile(p)


def isdir(p) -> int:
    """`posixpath.isdir(p)`: 1 or 0. CPython's, in `os.path.isdir`."""
    return os.path.isdir(p)


def islink(p) -> int:
    """`posixpath.islink(p)`: 1 or 0. CPython's, in `os.path.islink`."""
    return os.path.islink(p)


def lexists(p) -> int:
    """`posixpath.lexists(p)`: 1 or 0. CPython's, in `os.path.lexists`."""
    return os.path.lexists(p)


def samefile(a, b) -> int:
    """`posixpath.samefile(a, b)`: 1 or 0. CPython's, in `os.path.samefile`."""
    return os.path.samefile(a, b)


def getsize(p) -> int:
    """`posixpath.getsize(p)`. CPython's, in `os.path.getsize`."""
    return os.path.getsize(p)


# ── the constants, as the zero-argument functions this path spells them ─────
#
# Each forwards to `os`'s own function rather than repeating its literal, so
# there is ONE definition of each string in this tree. The `def` is not
# optional: a re-imported name is not in the export table (module docstring,
# "WHY EVERY FORWARD IS A `def`").

def sep() -> str:
    """`posixpath.sep`: `"/"`. A CONSTANT in CPython, a FUNCTION here.

    A module-level name has no storage across a dylib boundary, so every
    constant in this tree is a zero-argument function;
    `formal/hostmods/os/__init__.mojo` gives that at length.
    """
    return os.sep()


def curdir() -> str:
    """`posixpath.curdir`: `"."`. A CONSTANT in CPython, a FUNCTION here."""
    return os.curdir()


def pardir() -> str:
    """`posixpath.pardir`: `".."`. A CONSTANT in CPython, a FUNCTION here."""
    return os.pardir()


def extsep() -> str:
    """`posixpath.extsep`: `"."`. A CONSTANT in CPython, a FUNCTION here."""
    return os.extsep()


def pathsep() -> str:
    """`posixpath.pathsep`: `":"`. A CONSTANT in CPython, a FUNCTION here."""
    return os.pathsep()


def devnull() -> str:
    """`posixpath.devnull`: `"/dev/null"`. A CONSTANT in CPython, a FUNCTION
    here, forwarded from `os.devnull()`."""
    return os.devnull()
