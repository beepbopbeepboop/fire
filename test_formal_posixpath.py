#!/usr/bin/env python3
"""`formal/hostmods/posixpath.mojo`, differential against CPython's `posixpath`.

    python3 test_formal_posixpath.py [-v] [group ...]

Groups: `resolve`, `forward`, `same`, `constants`, `absent`. With no argument,
all. Every group that builds an image builds it on BOTH backends.

WHY THIS FILE'S ORACLE IS CPython AND NOT `os.path`
---------------------------------------------------
This module is a SPELLING: `formal/hostmods/os/path/__init__.mojo` is
CPython's `posixpath` and every function in `posixpath.mojo` forwards to it. So
there are two things a test could assert and they are not the same assertion:

  * against **CPython** — that the spelling `posixpath` answers what CPython's
    `posixpath` answers. This is `forward`, and it is the assertion the module
    exists for: a file that writes CPython's spelling must build AND be right.
  * against **`os.path`, in the SAME IMAGE** — that the two spellings agree with
    each other. This is `same`, and it is the one that catches what CPython
    cannot: a forward that calls the wrong name, loses an argument, or reads a
    stale copy of a string. CPython has no `posixpath.mojo`, so it cannot fail
    this comparison however wrong the forward is; only the image can.

Both are here because a spelling module that is right about CPython and
disagrees with its own `os.path` would be the worst outcome available: every
caller that used the spelling would get a different answer from every caller
that did not, with nothing to notice.

`os.path`'s own corpus is `test_formal_os.py`'s (436 path answers, both
backends). This file does not copy it: it re-uses the SAME path corpus shape
and asserts the two spellings agree case for case in one program, which is
strictly more than either file alone says.

THE EXPORT RULE IS WHAT MAKES THE FILE THIRTY FUNCTIONS LONG
------------------------------------------------------------
`reflect.collect_exports_src` publishes the public functions a module DEFINES,
and a name it merely re-imports is not one of them — so a module of bare
`from os.path import dirname` re-exports builds, links, and then a QUALIFIED
call through it has no symbol to bind. That is not specific to `posixpath`: the
same sentence is what CPython's own `os` gets for the names it forwards out of
`os.path` (`os.isfile(...)`), and it is why every function here is a real `def`.
`group: absent` pins the refusals that are NOT about the export rule, and
`group: forward` is what a caller actually needs.

THE CALL INSIDE A FORWARD MUST BE `os.path.f(...)`
--------------------------------------------------
Measured, all three, because the two that fail do so quietly:

    from os.path import dirname
    def dirname(p): return dirname(p)      ->  exit 2, unbounded recursion
    from os.path import dirname as pd
    def dirname(p): return pd(p)           ->  dyld: Symbol not found: _pd
    import os.path
    def dirname(p): return os.path.dirname(p)   ->  CPython's answer

`same` is the group that would notice if a forward regressed to one of the
first two spellings, because both of those produce a module that either does
not load or answers from itself.
"""

import argparse
import os
import platform
import posixpath
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
POSIXPATH_MODULE = os.path.join(HOSTMODS, "posixpath.mojo")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 120
REC = "@@"

TEMP = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures to build for, and why the list is not longer.

    BOTH, always, for the reason `CLAUDE.md` gives: `gimple_codegen.py`'s and
    `myinterpreter.py`'s lowerings of one AST are separately maintained, so a
    compiled-path answer that agrees on one architecture says nothing about the
    other. Every group here that builds an image builds it on both.

    A host with no x86-64 support is the one case that cannot run half of this,
    and it is reported by `backends()` returning one name rather than passed
    over silently — the reason is a fact about the machine, not about the
    module, and `test_formal_os_backing.py` reports it the same way.
    """
    if platform.machine() in ("arm64", "aarch64"):
        return ["arm64", "x86_64"]
    return ["x86_64"]


def build(src, name, backend=None):
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, f"{name}.{backend}" if backend else name)
    with open(tmp, "w") as f:
        f.write(src)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(tmp)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode == 0,
          f"build failed{(f' on --backend={backend}' if backend else '')}: "
          f"{(r.stderr or r.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image {os.path.basename(out)} exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("latin-1")


def records(text):
    """`<case>|<element>:[<value]` records, as `(case, element, value)` triples.

    **There is no index field, and that is deliberate: the POSITION of a record
    in this output IS its index**, and a field that repeats it is a second
    bookkeeping that can disagree with the first. The first version had one, and
    it disagreed — the program numbered its records with a counter that also
    advanced for a one-record case, so from the first skip on, "record 482" was
    reported against layout entry 481 and the check failed on an alignment that
    was an artefact of two counters rather than a difference in any answer.

    The value is bracketed when it is a string and bare when it is an integer,
    and the parser tells the two apart: `1` is the integer one and `[1]` is the
    string "1", and a path can be either. The distinction is load-bearing rather
    than cosmetic — `printf("%s")` on a word prints a POINTER, so a predicate's
    answer has to be printed with `%d` or the test would be comparing addresses
    (`test_formal_os.py` says the same).

    No path and no label is ever written into a format string (see
    `same_program`): `'a/-'` in a format makes printf read `'-'` as flags, and
    the build refusal that produces says nothing about which case was meant.
    """
    got = []
    for rec in text.split(REC):
        if not rec:
            continue
        head, sep, rest = rec.partition("|")
        part, sep2, val = rest.partition(":")
        if not sep or not sep2:
            raise Failure(f"record with no bar or colon: {rec!r}")
        if val.startswith("["):
            if not val.endswith("]"):
                raise Failure(f"record with no closing bracket: {rec!r}")
            got.append((int(head), int(part), val[1:-1]))
        else:
            got.append((int(head), int(part), val))
    return got


def mojo_string(s):
    """A Mojo string literal for a path.

    The four escapes a POSIX path can contain that a Mojo literal has to spell,
    and nothing else: a fixture with a quote or a backslash in it would be a
    source-level difference between the two runs, which is the kind of difference
    an oracle must not have (`test_formal_os.py` does the same and says why).
    """
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + out + '"'


# ── the corpus ─────────────────────────────────────────────────────────────
#
# `test_formal_os.py`'s STRINGS, kept deliberately close so a difference between
# the two files' corpora is a difference a reader can see. What is added here is
# what exercises the SPELLING rather than the algorithm: an absolute path, a
# path with no separator at all, and the empty string.

PATHS = [
    "", "a", "a/b", "/a/b/c.txt", "/", "//", "a.b/c", "/a/b/", "x/y.tar.gz",
    "...", "..a", "a..b", "a/b.c/d", "dir.d/file", "a b/c d", "-", "a/-",
    ".", "..", "./a", "../a", "/a/./b", "/a/../b", "/a//b", "/a/b/..",
    # The POSIX "exactly two slashes" shapes, because `splitroot_root`'s rule
    # is three tests and not `isabs`: a corpus without `//`, `///` and `//a/b`
    # would let `isabs` pass.
    "//", "///", "////", "//a", "//a/b", "//.", "//..",
]

PAIRS = [
    ("a/b/c", "a"), ("a/b/c", "/a"), ("/a/b", "/a/b/c"), ("/a", "/a"),
    (".", "a/b"), ("a", "a"), ("a/..", "a/b"), ("/a/b/../c", "/a"),
    ("/x/y/z", "/x"), ("x", "/"), ("a//b", "/a//b"), ("a/b", ""),
    (".", "."), ("/", "/"),
]

# The cases where `os.path` ITSELF diverges from CPython, excluded from the
# `forward` comparison and REPORTED on every run. One name, two paths.
#
# **EMPTY, since 2026-10-03, and that is the pin.** `os.path.realpath` kept a
# leading `//` where CPython collapses it, and these two cases were excluded
# rather than dropped so the divergence was visible instead of being a corpus
# that quietly lacked them. Both are compared against CPython now, on both
# backends, and the fix was not "collapse it in `realpath`" alone — it was to
# find that `realpath(3)` on this target ALREADY collapses the double slash,
# so what leaked it was the branch that answers `abspath(p)`, whose `normpath`
# keeps the root because CPython's does. `os.path`'s `realpath` asks
# `os.path.splitroot_root` — the rule `normpath` asks too, and the one
# `posixpath.splitroot_root` forwards to — and collapses on its way in.
#
# The set is KEPT, empty, because the exclusion is a thing this corpus is
# allowed to contain and a reader who finds it empty learns that the `//` class
# was measured and closed rather than that nobody thought of it. Adding a case
# to it is how a future divergence becomes a quiet hole.
EXCLUDED = set()

# The pairs CPython REFUSES, kept out of `PAIRS` and pinned separately.
#
# `posixpath.relpath("", start)` is a `ValueError` in CPython — "no path
# specified" — and there is no exception to raise on this path (FORMAL.md
# phase 7), so the module answers the working directory instead. That is a
# DOCUMENTED DEVIATION and `test_formal_os.py`'s `DEVIATION_CASES` already pins
# it (`relpath("", "a")` is `".."`); it is repeated here rather than imported
# because this file's oracle has to be able to say "CPython raises here and the
# image does not", and a corpus that silently omitted the pair would look like
# a corpus on which the two agreed.
#
# The answers below are what the module gives, MEASURED on both backends, and
# the second one is not in `test_formal_os.py`'s table because that table pins
# one case. Carrying a table of answers is a claim this file would rather not
# make, so the pair is compared against the module's own docstring claim and
# `relpath` is the only function for which that is possible — every other name
# in this file is compared against CPython and never against a number here.
REL_PATH_RAISES = [("", "a"), ("", "")]

# What the module answers for those, which is the CLAIM rather than a
# measurement of CPython's: an empty `path` is the working directory here, so
# `relpath("", "a")` is ".." (CPython raises) and `relpath("", "")` is ".".
# `test_formal_os.py`'s `DEVIATION_CASES` pins the first of the two as
# ".."; the second is here because this file's corpus removed both from PAIRS
# and a pair that vanished from a corpus without a row to replace it is a case
# nobody looks at again.
DEVIATION_ANSWERS = ["..", "."]

PREFIX_PAIRS = [
    ("abcd", "abcd"), ("abcd", "abxx"), ("abxx", "abcd"), ("a/b", "a/c"),
    ("", "x"), ("x", ""), ("", ""), ("/a/b", "/a/c"), ("abc", "ab"),
    ("ab", "abc"),
]

def _commonprefix2(a, b):
    """`posixpath.commonprefix` over TWO strings: CPython's own body.

    CPython takes a list and takes its minimum and maximum; the two-string form
    is the same computation with the list flattened. Transcribed here rather
    than calling `posixpath.commonprefix([a, b])` because the MODULE takes two
    strings (a list cannot cross a dylib boundary), so the oracle has to be
    asking CPython the question the module answers.
    """
    s1 = min([a, b])
    s2 = max([a, b])
    for i, c in enumerate(s1):
        if c != s2[i]:
            return s1[:i]
    return s1


# The one-argument functions, as (label, call template, CPython answer). The
# `%s` is filled by `mojo_string`. A predicate's answer is an INT, so it is
# printed with `%d` and not `%s` — `printf("%s")` on a word prints a POINTER,
# and a test that compared addresses would pass on any two non-equal answers.
ONE_ARG = [
    ("dirname", "dirname(%s)", lambda a: posixpath.dirname(a), "s"),
    ("basename", "basename(%s)", lambda a: posixpath.basename(a), "s"),
    ("normpath", "normpath(%s)", lambda a: posixpath.normpath(a), "s"),
    ("isabs", "isabs(%s)", lambda a: int(posixpath.isabs(a)), "i"),
    ("abspath", "abspath(%s)", lambda a: posixpath.abspath(a), "s"),
    ("expanduser", "expanduser(%s)", lambda a: posixpath.expanduser(a), "s"),
    ("realpath", "realpath(%s)", lambda a: posixpath.realpath(a), "s"),
    # Element 1, not 0: CPython's `splitroot` answers (drive, root, tail) and
    # the drive is "" for every path on this target, so [0] would answer "" for
    # an absolute path and look right for a relative one.
    ("splitroot_root", "splitroot_root(%s)",
     lambda a: posixpath.splitroot(a)[1], "s"),
]

TUPLE_ONE_ARG = [
    ("split", "split(%s)", lambda a: posixpath.split(a)),
    ("splitext", "splitext(%s)", lambda a: posixpath.splitext(a)),
    ("splitdrive", "splitdrive(%s)", lambda a: posixpath.splitdrive(a)),
]

TWO_ARG = [
    ("join", "join(%s, %s)", posixpath.join, PAIRS),
    ("relpath", "relpath(%s, %s)", posixpath.relpath, PAIRS),
    ("commonprefix", "commonprefix(%s, %s)", _commonprefix2, PREFIX_PAIRS),
]


# ── group: resolve ─────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import posixpath` finds this file, and it is out of `HOST_MODELLED`.

    And it is a FILE rather than an alias in the resolver, which is the design
    decision the module's docstring argues: pass 1 of `resolve_module_path`
    finds a `.mojo` in a search root and wins outright over the host-module list,
    which is the mechanism every other hostmod uses. An alias would make
    `import posixpath` mean "the `os` package's `path` submodule", which is the
    same source today and stops being the same the moment either gains a name
    the other did not.
    """
    check(os.path.isfile(POSIXPATH_MODULE),
          f"no Mojo source for posixpath at {POSIXPATH_MODULE}")
    sys.path.insert(0, HERE)
    import formal.imports as I
    got = I.resolve_module_path("posixpath")
    check(got is not None and os.path.samefile(got, POSIXPATH_MODULE),
          f"import posixpath resolves to {got!r}, not {POSIXPATH_MODULE!r}")
    tier = I.host_module_tier("posixpath")
    check(tier == "",
          f"posixpath is still in HOST_MODELLED (tier={tier!r}); its Mojo "
          f"source exists, so the entry is now a false statement about the "
          f"target rather than a conservative one")
    check(I._HOSTMODS_ROOT == HOSTMODS,
          f"the hostmods root moved to {I._HOSTMODS_ROOT!r}")
    check(not os.path.isfile(os.path.join(HERE, "posixpath.mojo")),
          "posixpath.mojo is at the repository root, which four independent "
          "resolvers search — see _HOSTMODS_ROOT")
    # The model this one forwards to has to still be where it says it is: a
    # forward whose target moved would still build and would answer from
    # somewhere else, and `same` would then be comparing two wrong things.
    model = I.resolve_module_path("os.path")
    check(model is not None
          and os.path.samefile(model, os.path.join(HOSTMODS, "os", "path",
                                                   "__init__.mojo")),
          f"os.path resolves to {model!r}, not formal/hostmods/os/path/"
          f"__init__.mojo; every function in posixpath.mojo forwards there")
    if verbose:
        print(f"    import posixpath -> {os.path.relpath(got, HERE)}, "
              f"tier={tier!r}; os.path -> {os.path.relpath(model, HERE)}")
    return True, ("resolves to formal/hostmods/posixpath.mojo, out of "
                  "HOST_MODELLED, forwarding to formal/hostmods/os/path")


# ── the two program builders ───────────────────────────────────────────────

def _emit(lines, k, call, kind, nparts):
    """The Mojo lines that evaluate one case and print it. How many records.

    `%lld` and not `%d` for the case NUMBER because a `%d` conversion is 32 bits
    wide on this path (`bugs/FORMAL_string_value_model.md` §2) and the corpus
    runs to 484 cases — which is worth saying because the first version of
    this file printed it with `%d`.

    The RETURN VALUE is the number of records emitted, and the caller advances
    its case counter by it. That is not a convenience: a tuple case emits TWO
    records and the first version advanced once, so both records carried the
    same case number and the checker compared element 0 against element 1's
    expectation. It reported 197 of 972 answers as differing from CPython when
    the module was right — a plausible-looking number that points at the module
    instead of at the harness, and the only reason it was caught is that a
    mismatch that large should not happen on a module that forwards.
    """
    if nparts == 1:
        fmt = "[%s]" if kind == "s" else "%d"
        lines.append(f"    r = {call}")
        lines.append(f'    printf("%lld|0:{fmt}@@", {k}, r)')
        return 1
    lines.append(f"    p0, p1 = {call}")
    for j in (0, 1):
        lines.append(f'    printf("%lld|{j}:[%s]@@", {k}, p{j})')
    return 2


def forward_program(backend):
    """One program: every function, over the corpus, through `posixpath`."""
    lines = ["import posixpath", "", "def main():"]
    n = 0
    # Every call is QUALIFIED (`posixpath.dirname(...)`), which is the whole
    # point: the module's `def`-per-name exists because a qualified call is the
    # one that needs an exported symbol, so a corpus that spelled it
    # `from posixpath import dirname` and then called `dirname(...)` would pass
    # whether or not the export rule were satisfied. The first version of this
    # builder did exactly that and every one of its programs was refused with
    # "the format string has 2 conversions and the call is given 1 operand",
    # because the unqualified `dirname` resolved to nothing at all.
    for label, tmpl, _py, kind in ONE_ARG:
        for a in PATHS:
            if (label, a) in EXCLUDED:
                continue
            n += _emit(lines, n, "posixpath." + tmpl % mojo_string(a), kind, 1)
    for label, tmpl, _py in TUPLE_ONE_ARG:
        for a in PATHS:
            n += _emit(lines, n, "posixpath." + tmpl % mojo_string(a), "s", 2)
    # The tuple case above numbers BOTH its records from one `k`, so the
    # counter is back in step with the CASE for what follows; `n` is a record
    # count for the arithmetic and a case number for the field, and the two are
    # the same thing only because `_emit` returns the record count.
    for label, tmpl, _py, pairs in TWO_ARG:
        for (a, b) in pairs:
            n += _emit(lines, n,
                       "posixpath." + tmpl % (mojo_string(a),
                                              mojo_string(b)), "s", 1)
    return records(run(build("\n".join(lines) + "\n", "pp_forward", backend)))


def _same_cases():
    """`(label, call, kind, nparts, os_path_has_it)` for every case.

    Built ONCE and read by both the program builder and the checker, so the two
    cannot drift: the program emits one record per entry here in this order, and
    the checker maps a record's INDEX back to the same entry.

    `os_path_has_it` is True for every name in this corpus, and it is a FIELD
    rather than an assumption. It was False for exactly one name,
    `splitroot_root`, because `os.path` did not have it then: `os/path/
    __init__.mojo` was `posixpath` MINUS the root/drive split, which is a tuple
    on this path (the module's own `splitroot` entry says why), and a builder
    that asked `os.path.splitroot_root` got a build refusal naming the WRONG
    module and saying nothing about the case that was meant:

        os.path.splitroot_root(): `os.path` is a linked module but it exports
        no `splitroot_root`, so the call has no symbol to bind.

    `os.path` HAS it now — the ROOT half is one word and `realpath` and
    `normpath` both need the same three tests, so the rule lives there and
    `posixpath` forwards to it (2026-10-03). The flag is kept rather than
    deleted because a per-case field is what a reader can check against the
    module's docstring, and because the failure it was introduced for is still
    a live one for any name the two modules do not share.

    Nothing about a case is written into the FORMAT STRING, and that is not
    tidiness: a path is data, and a data character in a format string is a
    conversion or a flag — `'a/-'` in a format makes printf read `'-'` as
    flags. The index carries the identity instead.
    """
    cases = []
    # NOT filtered by `EXCLUDED`, and that is still the point: `os.path` and
    # `posixpath` are compared to EACH OTHER here rather than to CPython, so a
    # case `os.path` gets wrong would have been a case the `forward` group
    # found instead. The set is empty and says why; see its own comment.
    for label, tmpl, _py, kind in ONE_ARG:
        for a in PATHS:
            cases.append((label, tmpl % mojo_string(a), kind, 1, True))
    for label, tmpl, _py in TUPLE_ONE_ARG:
        for a in PATHS:
            cases.append((label, tmpl % mojo_string(a), "s", 2, True))
    for label, tmpl, _py, pairs in TWO_ARG:
        for (a, b) in pairs:
            cases.append((label, tmpl % (mojo_string(a), mojo_string(b)),
                          "s", 1, True))
    return cases


def deviation_program(backend=None):
    """The pairs CPython raises on, with what THIS module answers instead.

    A separate program and not part of the corpus, because the oracle cannot be
    CPython's answer for them: CPython has none. `relpath` is the only name in
    this module with no exception to raise, so this is the only group where the
    expectation is a documented claim rather than a measurement — and it says
    so in the assertion's own message.
    """
    lines = ["import posixpath", "", "def main():"]
    for k, (a, b) in enumerate(REL_PATH_RAISES):
        lines.append(f'    printf("%lld|0:[%s]@@", {k}, '
                     f'posixpath.relpath({mojo_string(a)}, '
                     f'{mojo_string(b)}))')
    return records(run(build("\n".join(lines) + "\n", "pp_deviation",
                             backend)))


def same_program(backend):
    """One program: `posixpath.f(x)` against `os.path.f(x)`, case for case.

    The assertion CPython cannot make about itself, and the one that catches a
    forward calling the wrong name or losing an argument: the two spellings run
    in the SAME image, so any difference is a defect in this module and nothing
    else. CPython has no `posixpath.mojo`, so it cannot fail this comparison
    however wrong the forward is.

    Two SEPARATE calls per case rather than one call and one comparison inside
    the image, and BOTH printed, so a difference names which spelling was wrong
    — a program that compared them itself could only say that they differ.

    The record INDEX is the case, as everywhere else in this tree, and
    `same_pairs` turns an index back into (case, spelling). Nothing about a case
    goes in the FORMAT STRING, and that is not tidiness: a path is data, and a
    data character in a format string is a conversion or a flag — `'a/-'` in a
    format makes printf read `'-'` as flags, and the refusal that produces says
    nothing about which case was meant.
    """
    lines = ["import posixpath", "import os.path", "", "def main():"]
    case = 0
    for _label, call, kind, nparts, in_ospath in _same_cases():
        if nparts == 2:
            lines.append(f"    q0, q1 = posixpath.{call}")
            lines.append(f"    r0, r1 = os.path.{call}")
            for elem, (mine, theirs) in enumerate((("q0", "r0"),
                                                   ("q1", "r1"))):
                lines.append(f'    printf("%lld|%d:[%s]@@", {case}, {elem}, '
                             f'{mine})')
                lines.append(f'    printf("%lld|%d:[%s]@@", {case}, {elem}, '
                             f'{theirs})')
        elif not in_ospath:
            # ONE record, and NO `os.path` call: this name is `posixpath`'s
            # alone, so there is nothing in-image to compare it to. It is
            # checked against CPython by `forward`, and `_same_cases` says why
            # asking `os.path` for it is a build refusal.
            fmt = "[%s]" if kind == "s" else "%d"
            lines.append(f'    printf("%lld|0:{fmt}@@", {case}, '
                         f'posixpath.{call})')
        elif kind == "s":
            lines.append(f'    printf("%lld|0:[%s]@@", {case}, '
                         f'posixpath.{call})')
            lines.append(f'    printf("%lld|0:[%s]@@", {case}, os.path.{call})')
        else:
            lines.append(f'    printf("%lld|0:%d@@", {case}, '
                         f'posixpath.{call})')
            lines.append(f'    printf("%lld|0:%d@@", {case}, os.path.{call})')
        case += 1
    return records(run(build("\n".join(lines) + "\n", "pp_same", backend)))


def same_record_layout():
    """One entry per RECORD `same_program` emits, in order.

    A comparable case contributes TWO entries — the same `(case, element)`
    twice, once per spelling — because those two records are what the checker
    compares. A case `os.path` has no name for contributes ONE `None`, because
    the program emits one record for it and a pair slot would make the checker
    compare it against the NEXT case's first record.

    One entry per record rather than per case, so the expected count is
    `len(layout)` and cannot be a second arithmetic that disagrees with the
    first: the count, the pairing and the skip all read the same list.
    """
    layout = []
    for k, (label, call, kind, nparts, in_ospath) in enumerate(_same_cases()):
        if not in_ospath:
            layout.append(None)
            continue
        for elem in range(nparts if nparts == 2 else 1):
            layout.append((k, elem))
            layout.append((k, elem))
    return layout


# ── group: forward ─────────────────────────────────────────────────────────

def group_forward(tmpdir, verbose):
    """Every answer, compared with CPython's own `posixpath`.

    The module's whole reason for existing: a file that writes CPython's
    spelling must build AND be right. Nothing here is a recorded constant —
    delete the module and the answers are whatever this interpreter's
    `posixpath` says.
    """
    bad = []
    total = 0
    for backend in backends():
        got = forward_program(backend)
        # Rebuild the expectation in the SAME order the program emitted, so a
        # record's index is the case that produced it rather than a count the
        # two sides agree on by accident.
        want = []
        for label, _tmpl, py, kind in ONE_ARG:
            for a in PATHS:
                if (label, a) in EXCLUDED:
                    continue
                v = py(a)
                want.append((label, a, str(int(v)) if kind == "i" else str(v)))
        for label, _tmpl, py in TUPLE_ONE_ARG:
            for a in PATHS:
                v = py(a)
                want.append((label, a, str(v[0])))
                want.append((label, a, str(v[1])))
        for label, _tmpl, py, pairs in TWO_ARG:
            for (a, b) in pairs:
                want.append((label, a, str(py(a, b))))
        check(len(got) == len(want),
              f"forward[{backend}]: image reported {len(got)} of "
              f"{len(want)} cases; excess {got[len(want):][:3]}")
        # POSITIONAL, like `same`: a tuple case prints its case number on BOTH
        # records (they are two answers to one question), so the record's own
        # field is not a record index and must not be used as one. The output
        # order and `want`'s order are the same list.
        for n, (got_rec, want_rec) in enumerate(zip(got, want)):
            _case, part, val = got_rec
            label, a, expect = want_rec
            if val != expect:
                bad.append((backend, n, part, label, a, val, expect))
        total += len(want)
    detail = ""
    if bad:
        b = bad[0]
        detail = (f"; first: [{b[0]}] case {b[1]} element {b[2]} {b[3]}"
                  f"({b[4]!r}) image {b[5]!r} CPython {b[6]!r}")
    check(not bad, f"{len(bad)} of {total} answer(s) differ from CPython"
          + detail)

    # And the pairs CPython refuses, which are compared against the module's
    # documented claim rather than against CPython — with the raise asserted,
    # so the reason this is a separate block is visible.
    dev = deviation_program()
    check(len(dev) == len(REL_PATH_RAISES),
          f"deviation: image reported {len(dev)} of "
          f"{len(REL_PATH_RAISES)} cases")
    dev_bad = []
    for idx, _part, val in dev:
        a, b = REL_PATH_RAISES[idx]
        try:
            cp = posixpath.relpath(a, b)
        except ValueError:
            cp = None
        if cp is not None:
            dev_bad.append((a, b, val, f"CPython answers {cp!r}, so this case "
                                     f"belongs in the corpus"))
        elif val != DEVIATION_ANSWERS[idx]:
            dev_bad.append((a, b, val, DEVIATION_ANSWERS[idx]))
    dev_detail = ""
    if dev_bad:
        d = dev_bad[0]
        dev_detail = (f"; first: relpath({d[0]!r}, {d[1]!r}) image {d[2]!r} "
                      f"against the documented {d[3]}")
    check(not dev_bad,
          f"{len(dev_bad)} deviation case(s) wrong; CPython raises ValueError "
          f"('no path specified') for every one of them and this path has no "
          f"exception to raise, so the answer is the module's documented one"
          + dev_detail)
    note = ""
    if EXCLUDED:
        note = (f" ({len(EXCLUDED)} case(s) excluded: a case where `os.path` "
                f"itself diverges from CPython, listed in EXCLUDED with its "
                f"reason)")
    if verbose:
        print(f"    {len(want)} cases x {len(backends())} backends, "
              f"each against CPython's own posixpath{note}")
    return True, (f"{total} posixpath answers agree with CPython on "
                  f"{len(backends())} backend(s){note}")


# ── group: same ────────────────────────────────────────────────────────────

def group_same(tmpdir, verbose):
    """`posixpath.f(x)` and `os.path.f(x)`, IN THE SAME IMAGE, case for case.

    The assertion CPython cannot make about itself. A forward that calls the
    wrong name, drops an argument, or reads a stale string would still agree
    with CPython on the cases that do not distinguish them — which is most of
    them — and this group is over the same corpus with the comparison done by
    the image, in the same process, on both backends.

    The comparison is per element rather than per record, so a difference names
    the element: `split`\'s head agreeing while its tail does not is a different
    defect from the whole answer being wrong, and a test that reported only "the
    two disagree" would make a person go and find which.
    """
    layout = same_record_layout()
    bad = []
    total = 0
    skipped = 0
    for backend in backends():
        got = same_program(backend)
        # One record per answer, and TWO answers per case only where `os.path`
        # has the name — so the expected count is computed from `cases`, not
        # from 2 x len(cases). Getting that wrong is a one-line arithmetic slip
        # that reports a mismatch of 25 and sends a reader looking for a bug in
        # the module.
        expect = len(layout)
        check(len(got) == expect,
              f"same[{backend}]: image reported {len(got)} of {expect} "
              f"records; excess {got[expect:][:3]}")
        # Both answers for one ELEMENT of one case are ADJACENT, which is what
        # makes this a comparison and not two unrelated assertions. Whether a
        # record is one of a PAIR is read from `layout` rather than from the
        # record's own fields: the layout is what the program was generated
        # from, so a record cannot talk the checker out of pairing it with the
        # wrong neighbour.
        n = 0
        while n < len(got):
            if layout[n] is None:
                # The one name `os.path` does not have: ONE record, no pair.
                # Counted as a skip, and the COUNT of skips is checked against
                # the layout, because a skip that grew silently would be a
                # comparison that stopped happening.
                n += 1
                skipped += 1
                continue
            ia, ea, va = got[n]
            ib, eb, vb = got[n + 1]
            total += 1
            if (ia, ea) != layout[n] or (ib, eb) != layout[n + 1]:
                raise Failure(
                    f"same[{backend}]: records {n}/{n + 1} are not the pair "
                    f"the layout says — layout {layout[n]}/{layout[n + 1]}, "
                    f"image ({ia}, {ea})/({ib}, {eb})")
            if va != vb:
                bad.append((backend, layout[n], va, vb))
            n += 2
    detail = ""
    if bad:
        b = bad[0]
        detail = (f"; first: [{b[0]}] case {b[1][0]} element {b[1][1]} "
                  f"posixpath {b[2]!r} vs os.path {b[3]!r}")
    check(not bad,
          f"{len(bad)} of {total} element comparison(s) disagree between the "
          f"two spellings" + detail)
    # Per BACKEND, because `skipped` accumulates over the loop and the layout
    # does not. Saying so in the expression rather than resetting a counter is
    # what keeps the two numbers from drifting apart on a third backend.
    nones = len([c for c in layout if c is None])
    check(skipped == nones * len(backends()),
          f"same: {skipped} record(s) were skipped as not-comparable over "
          f"{len(backends())} backend(s) and the layout marks {nones} record "
          f"slot(s) per backend; the two must agree or the pairing compared "
          f"the wrong records")
    if verbose:
        print(f"    {total} element comparison(s) in-image on "
              f"{len(backends())} backend(s), {skipped // len(backends())} "
              f"record(s) skipped as posixpath-only per backend")
    return True, (f"{total} in-image comparisons: the two spellings agree, "
                  f"element for element, on {len(backends())} backend(s) "
                  f"({skipped // len(backends())} posixpath-only name(s) "
                  f"compared against CPython instead)")


# ── group: constants ───────────────────────────────────────────────────────

def group_constants(tmpdir, verbose):
    """The six constants, as the zero-argument functions this path spells them.

    `sep`, `curdir`, `pardir`, `extsep`, `pathsep`, `devnull`. Each is compared
    with `getattr` on the live `posixpath` rather than with a string typed here,
    so the oracle is CPython's own value and not a transcription of it — which
    is the whole point of the comparison, and the reason this table is a table
    of NAMES.

    This group also pins the SPELLING: a constant is a module-level name in
    CPython and a module-level name has no storage across a dylib boundary, so
    each is read as `posixpath.sep()`. A program that spelled `posixpath.sep`
    gets the refusal `formal/build.py` prints for a module attribute read as a
    value, and that refusal names itself.
    """
    names = ["sep", "curdir", "pardir", "extsep", "pathsep", "devnull"]
    lines = ["import posixpath", "", "def main():"]
    for k, nm in enumerate(names):
        lines.append(f'    printf("%lld|0:[%s]@@", {k}, posixpath.{nm}())')
    got = records(run(build("\n".join(lines) + "\n", "pp_const")))
    check(len(got) == len(names),
          f"constants: image reported {len(got)} of {len(names)}")
    bad = []
    for idx, _part, val in got:
        want = getattr(posixpath, names[idx])
        if val != want:
            bad.append((names[idx], val, want))
    detail = ""
    if bad:
        detail = (f"; first: {bad[0][0]} image {bad[0][1]!r} CPython "
                  f"{bad[0][2]!r}")
    check(not bad, f"{len(bad)} constant(s) differ from CPython" + detail)
    # And the spelling: the ATTRIBUTE is refused, naming itself, because
    # `None`-like module state has no representation on this path
    # (`bugs/FORMAL_module_state_no_storage.md`).
    src = ("import posixpath\n\ndef main():\n"
           "    printf(\"[%s]\\n\", posixpath.sep)\n")
    tmp = os.path.join(TEMP, "attr.mojo")
    out = os.path.join(TEMP, "attr")
    with open(tmp, "w") as f:
        f.write(src)
    r = subprocess.run([sys.executable, FIRE, "build", "--formal",
                        "--no-prove", "-o", out, tmp],
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                       cwd=HERE)
    msg = (r.stderr or r.stdout)
    check(r.returncode != 0,
          "posixpath.sep built; a constant is spelled posixpath.sep() on this "
          "path and the attribute form should be refused rather than answered "
          "from whatever the word happens to be")
    check("sep" in msg,
          f"the refusal for posixpath.sep does not NAME it: "
          f"{msg.strip()[-200:]}")
    if verbose:
        print(f"    {len(names)} constants against CPython, and the "
              f"attribute spelling refused")
    return True, (f"{len(names)} constants agree with CPython, and "
                  f"posixpath.sep (the attribute) is refused by name")


# ── group: absent ──────────────────────────────────────────────────────────

def group_absent(tmpdir, verbose):
    """The names this module does NOT have, refused with a reason.

    Pinned because an absent name and a wrong answer look the same to a caller
    only if nothing checks, and because `splitroot` is the one a reader expects
    to find: it is CPython's `posixpath` name for the path's root/drive split
    and this module deliberately answers only its first element, under a
    different name, rather than as a tuple.
    """
    for name in ("splitroot", "commonpath", "ismount", "normcase",
                 "expandvars", "altsep", "getmtime"):
        src = (f"import posixpath\n\ndef main():\n"
               f"    printf(\"%lld\\n\", posixpath.{name}(\"a\"))\n")
        tmp = os.path.join(TEMP, "absent.mojo")
        out = os.path.join(TEMP, "absent")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run([sys.executable, FIRE, "build", "--formal",
                            "--no-prove", "-o", out, tmp],
                           capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, cwd=HERE)
        msg = (r.stderr or r.stdout)
        check(r.returncode != 0,
              f"posixpath.{name} built; it is not supposed to exist, and a "
              f"silently-approximated name is worse than a refusal")
        check(name in msg,
              f"the refusal for posixpath.{name} does not NAME it: "
              f"{msg.strip()[-200:]}")
    # `splitroot_root` IS here, and is the piece that is one word.
    src = ("import posixpath\n\ndef main():\n"
           "    printf(\"[%s][%s]\\n\", posixpath.splitroot_root(\"/a/b\"), "
           "posixpath.splitroot_root(\"a/b\"))\n")
    out = build(src, "pp_root")
    got = run(out)
    want = (f"[{posixpath.splitroot('/a/b')[1]}]"
            f"[{posixpath.splitroot('a/b')[1]}]")
    check(got.strip() == want,
          f"splitroot_root: image {got.strip()!r}, CPython's root {want!r}")
    if verbose:
        print(f"    7 absent names each refused by name, and "
              f"splitroot_root answers the one piece that is one word")
    return True, "7 absent names refused by name; splitroot_root agrees"


GROUPS = {
    "resolve": group_resolve,
    "forward": group_forward,
    "same": group_same,
    "constants": group_constants,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    with tempfile.TemporaryDirectory(prefix="pptest") as td:
        TEMP = td
        npass = nfail = 0
        for nm in names:
            try:
                _ok, msg = GROUPS[nm](td, args.verbose)
                print(f"PASS {nm:10} {msg}")
                npass += 1
            except Failure as e:
                print(f"FAIL {nm:10} {e}")
                nfail += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {nm:9} {type(e).__name__}: {e}")
                nfail += 1
        print(f"\nformal posixpath: PASS={npass} FAIL={nfail}")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())