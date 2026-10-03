# FORMAL_os_path_realpath_keeps_a_double_slash_root: `os.path.realpath("//a")` answers `//a`, CPython answers `/a`

**Found 2026-10-03** while writing `formal/hostmods/posixpath.mojo` and its
differential test. Not mine and not fixed here: the model is
`formal/hostmods/os/path/__init__.mojo`'s, its test is `test_formal_os.py`'s,
and both are owned by the `module:platform+fnmatch+collections-rest` /
`formal-os` rows. What is here is the measurement, because the reason nobody
had measured it is a corpus gap and the gap is the finding.

## What I ran, and what it said

`formal/hostmods/posixpath.mojo` forwards every name to `os.path`, so a
`posixpath` differential test that compares against CPython is ALSO a test of
`os.path` — which is how this was found. One program, one case list, both
spellings, both backends:

    import os.path
    import posixpath

    def main():
        printf("%lld|0:[%s]@@", 0, os.path.realpath("//a"))
        printf("%lld|1:[%s]@@", 0, posixpath.realpath("//a"))
        printf("%lld|0:[%s]@@", 1, os.path.realpath("//a/b"))
        printf("%lld|1:[%s]@@", 1, posixpath.realpath("//a/b"))
        printf("%lld|0:[%s]@@", 2, os.path.realpath("///a"))
        printf("%lld|1:[%s]@@", 2, posixpath.realpath("///a"))

    $ python3 fire.py build --formal --no-prove -o img main.mojo && ./img
    0|0:[//a]@@0|1:[//a]@@1|0:[//a/b]@@1|1:[//a/b]@@2|0:[/a]@@2|1:[/a]@@
    3|0:[//]@@3|1:[//]@@4|0:[//x]@@4|1:[//x]@@

against CPython's own, in this process:

    >>> [posixpath.realpath(p) for p in ("//a", "//a/b", "///a", "//", "//x")]
    ['/a', '/a/b', '/a', '/', '/x']

So **`os.path.realpath` keeps the double slash and CPython removes it**, on
exactly the paths that begin with `//` and not `///`. Both spellings agree
with EACH OTHER on every case (`|0` and `|1` match throughout), which is the
part that says this is `os.path`'s answer and not a forwarding defect: a
`posixpath` bug would show the two spellings disagreeing.

## Why

`formal/hostmods/os/path/__init__.mojo`'s `realpath` is a call to the C
library's `realpath(3)` (`formal/hostmods/os/_syscalls.mojo`'s `fs_realpath`),
and that is the RIGHT primitive for what `realpath` means — resolving
symlinks needs the kernel. The divergence is that **macOS's `realpath(3)`
implements the POSIX rule that a path beginning with EXACTLY TWO slashes is
implementation-defined**, and keeps them; CPython's `posixpath.realpath` does
not call `realpath(3)` at all. It resolves lexically, component by component,
over `os.lstat`, and its own comment says so:

    # `realpath()` doesn't use the C library version, because on macOS
    # it behaves differently when the path doesn't exist.

so the two implementations disagree about more than the nonexistent-path case,
and the `//` case is the one that shows up in a corpus with no `//` in it.

CPython is the oracle this project holds itself to (`CLAUDE.md`: "the
strongest cheap parity check available and the only one that is not this
project grading itself"), so `'/a'` is the right answer and `realpath(3)` is
not sufficient to produce it.

## Why nobody had measured it: the corpus gap IS the finding

`test_formal_os.py`'s `STRINGS` corpus — 24 paths, run over every one-argument
function and both backends — has no entry that begins with `//`. It has `"/"`,
`"//"` is absent, `"a//b"` and `"/a//b"` are present (an INTERIOR double slash,
which both implementations normalise identically), and that is enough for every
other function in the module and not enough for this one.

So the measurement to make first is not "fix `realpath`", it is **add the
`//`-shaped paths to `test_formal_os.py`'s corpus and see what else moves**.
Three cases are the obvious addition, and they are the ones that separate the
POSIX classes:

    "//"      ->  '/'      (exactly two: implementation-defined)
    "//a/b"   ->  '/a/b'
    "///a"    ->  '/a'     (three or more: ordinary root)
    "////"    ->  '/'      (POSIX: exactly two is special, four is not)

**`normpath` is the case to check FIRST and it is a separate question from
`realpath`'s.** `normpath` is pure string arithmetic and its answer for `//a` is
its own; if `normpath("//a")` already answers `/a` then the module knows the
rule and `realpath` simply does not apply it, which is a one-function fix. If
`normpath("//a")` answers `//a` too, then the rule is missing from the module
rather than from one function, and the corpus addition would say so. I did not
measure that — it is inside `test_formal_os.py`'s ownership and outside what
this task's change can reach, so it is the first thing whoever owns that file
should run:

    # on this tree, arm64, before changing anything
    #   printf("[%s]\n", os.path.normpath("//a"))
    #   printf("[%s]\n", os.path.normpath("///a"))

## The shape of the fix, and the trap in it

The honest fix is a lexical collapse of a leading `//` in `realpath`'s own
code, around the `realpath(3)` call, because the kernel call cannot be asked to
do it:

    POSIX reserves a leading "//" and realpath(3) honours that; CPython's
    posixpath does not, so the leading run of slashes is collapsed to one
    BEFORE the call and the answer is then prefixed back.

The trap is that the collapse must apply to exactly the POSIX case: `//` and
`//a/b` collapse, `///a` does not. **The same three-test rule
`formal/hostmods/posixpath.mojo`'s `splitroot_root` implements** —
not-a-slash gives `""`, `//`-and-not-a-third-slash gives `"//"`, otherwise
`"/"` — is the rule, and that function already has it, with the measurement in
its docstring. So the rule is written down and tested in this tree; what is
missing is its application inside `os/path/__init__.mojo`'s `realpath`, and a
call from `os.path` into `posixpath.mojo` would be the WRONG direction (it
would make the lower layer depend on a module that forwards to it). The rule
belongs in `os/path/__init__.mojo`, and `posixpath.mojo`'s `splitroot_root`
should then forward to it rather than carrying its own copy — which is a
deduplication this doc is asking for, not a new function to write twice.

## What `posixpath.mojo` does about it in the meantime

`test_formal_posixpath.py`'s `forward` group carries the two `//`-shaped
`realpath` cases as an EXCLUDED pair with the reason printed on a verbose run
and the exclusion stated in the group's own docstring, so:

  * the test is green and the rest of the corpus (972 answers over 25 paths and
    13 names, on both backends) is still compared against CPython;
  * the exclusion is VISIBLE — the group reports `2 case(s) excluded, see
    bugs/FORMAL_os_path_realpath_keeps_a_double_slash_root.md` — rather than
    being a corpus quietly missing a case;
  * the moment `os.path.realpath` is fixed, `splitroot_root`'s rule is the one
    to reuse and this doc's "shape of the fix" section is where that is said.

`same` (which compares `posixpath.f(x)` against `os.path.f(x)` in one image) is
NOT excluded for these cases, and that is deliberate: the two spellings DO agree
here, and a spelling module must not inherit a divergence as if it were its
own. The divergence belongs to `os.path` and is filed against `os.path`.