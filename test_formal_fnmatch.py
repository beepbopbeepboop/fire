#!/usr/bin/env python3
"""Build `fnmatch` for the formal backend and RUN it, compared with CPython.

    python3 test_formal_fnmatch.py [-v] [group ...]

Groups: `resolve`, `match`, `cross`. With no argument, all of them.

Why an oracle rather than a table. Every case is computed twice — once through
`python3 fire.py build --formal --no-prove` and executed, once through
`fnmatch` in this process — and the two have to agree. Nothing here states what
`fnmatch.fnmatch("a/b.py", "*.py")` is; it asks. Pattern answers are one bit, so
a table of them would be exactly the kind of thing that is right on the inputs
you tried and wrong on the one you did not, and a wrong bit here is a program
that globs the wrong files.

CPython is asked BOTH questions for every case — `fnmatch` and `fnmatchcase` —
and the image has to agree with both. That is not redundancy: on a POSIX target
CPython's `fnmatch` is `fnmatchcase(normcase(a), normcase(b))` and
`os.path.normcase` is the identity, so the two must agree, and the module
implements that by delegation rather than by a second copy of the walk. A test
that asked only one of them would not notice a copy that case-folded.

THE `cross` GROUP IS THE ONE THAT PINS THE FLAG. `formal/hostmods/fnmatch.mojo`
and `formal/hostmods/pathlib.mojo` share one matcher, and the only difference
between their two entry points is whether `*` may consume a `/`. So the same
pairs are put through both, and every pair in the corpus is one CPython answers
DIFFERENTLY for the two functions:

    fnmatch.fnmatch("a/b.py", "*.py")           1
    pathlib.PurePosixPath("a/b.py").match("*.py") 0

A matcher that ignored the flag would fail this group on its first case, which
is the assertion the flag exists for.

The corpus and the record plumbing are IMPORTED from `test_formal_json.py`
rather than copied, for the reason `test_formal_pathlib.py` gives: a second copy
of the mask is a second spelling of "a byte a source literal cannot hold", and
the first version of `json`'s mask had a bug in it that a copy would have
inherited silently.
"""
import argparse
import fnmatch
import os
import pathlib
# `subprocess` was imported here and read NOTHING through it. A dead import
# blocks a file on the formal path for exactly the reason an absent module
# does, which is why `tools/formal_host_import_shapes.py` gives it a shape
# (`DEAD`) rather than counting it as a use; see
# `bugs/FORMAL_a_call_result_field_access_has_no_representation.md` §3.
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

from test_formal_json import (Failure, build, check, mask, mj,  # noqa: E402
                              records, run, REC)
import test_formal_json as J  # noqa: E402

TEMP = None

# The unmask, with the module it asks for filled in — the two host modules
# export the byte helpers under their own names (`json.byte_at` /
# `fnmatch.byte_or`) and the mask cannot tell which module it is building an
# input for, so the name is a parameter rather than a second copy. The
# `~xHH` arm needs a hex-digit reader that `fnmatch` has no reason to export,
# and no case in this corpus uses one (they are all printable patterns and
# names), so it is REPLACED with a NUL that would truncate and fail loudly
# rather than decode to something plausible — `test_formal_pathlib.py`'s
# arrangement, and for its reason.
# `fnmatch` needs no byte WRITES — it reads bytes and answers a bit — so unlike
# `json` and `pathlib` it exports no `put_byte`, and the mask's store arm is
# rewritten as a direct `Pointer[UInt8]` store rather than the module growing an
# export only a test would call. That is also why the `~xHH` arm below is
# REPLACED and not given a reader: no case in this corpus uses one (they are all
# printable patterns and names), and an arm that truncated a case would fail
# loudly rather than decode to something plausible.
_UNMASK = J.UNMASK.replace("json.byte_at", "%(mod)s.byte_or")
_UNMASK = _UNMASK.replace("json.put_byte(out, u, ", "_put(out, u, ")
_UNMASK = _UNMASK.replace("json.", "%(mod)s.")
_UNMASK = _UNMASK.replace(
    """            var h = 16 * %(mod)s.hexdig(%(mod)s.byte_or(t, i + 2)) + %(mod)s.hexdig(%(mod)s.byte_or(t, i + 3))
            u = _put(out, u, h)""",
    """            u = _put(out, u, 0)""")
# The store itself is `json.mojo`'s `put_byte` idiom, verbatim: a one-byte
# buffer, `memset` into it, `memcpy` it out. It was here because a direct
# `q.value() = b` was REFUSED on this path (an assignment target had to be a
# plain name), which is why three host modules carried the same four lines
# rather than one of them carrying a helper the others call. The store exists
# now — `model.pointer_store_lowering`, the store mirror of the pointer value
# model's load, on both backends — and these modules can be shortened to
# `out.value() = b` whenever someone owns that; nothing here depends on the
# round trip through `malloc`, so leaving it is a cleanup and not a fix.
_UNMASK = ("def _put(out, at, b) -> int:\n"
           "    var one: Pointer[UInt8] = malloc(1)\n"
           "    memset(one, b & 255, 1)\n"
           "    memcpy(out + at, one, 1)\n"
           "    return at + 1\n") + _UNMASK

SPLIT = J.SPLIT.replace("json.byte_at", "fnmatch.byte_or")
SPLIT = SPLIT.replace("json.", "fnmatch.")


# ── the corpora ────────────────────────────────────────────────────────────
#
# Written for the RULES, one cluster per rule, because the answer is one bit
# and a failure has to say WHICH rule. Every case is a (name, pattern) pair.
PAIRS = [
    # `*`: any run, including none; more than one; and the two shapes that
    # separate a backtracking walk from a naive one — a `*` that has to give
    # characters back to a following literal, and two of them.
    ("a.py", "*.py"), ("a.py", "*"), ("", "*"), ("a", "*"), ("a", "**"),
    ("abc", "*"), ("abc", "*b*"), ("abc", "*b"), ("abc", "a*c"),
    ("abc", "a**c"), ("abc", "*a*b*c"), ("abc", "a*b*c"), ("abc", "a**"),
    ("abc", "*abc"), ("abc", "abc*"), ("abc", "*a*"), ("abc", "a*c*"),
    ("", ""), ("a", ""), ("", "a"), ("a", "a"), ("a", "A"), ("A", "a"),
    # `?`: exactly one character, and one that is not there.
    ("a", "?"), ("ab", "?"), ("abc", "a?c"), ("abc", "a?"), ("a", "??"),
    ("", "?"), ("a", "a?"), ("ab", "a?"),
    # `[seq]`, `[!seq]`, `[!]seq]`, a range, and `]` as a literal first.
    ("a", "[abc]"), ("d", "[abc]"), ("a", "[!abc]"), ("d", "[!abc]"),
    ("a", "[^abc]"), ("d", "[^abc]"), ("b", "[a-c]"), ("d", "[a-c]"),
    ("-", "[a-c]"), ("c", "[a-c]"), ("b", "[a-c-e]"), ("]", "[]]"),
    ("]", "[!]]"), ("a", "[]]a"), ("a", "[!]]"), ("b", "[!]]"),
    ("-", "[-]"), ("-", "[a-]"), ("a", "[a-]"), ("-", "[--0]"),
    ("a", "[abc"), ("[", "[abc"), ("a", "[a"), ("[", "["), ("a[", "a["),
    ("a", "[!"), ("!", "[!"), ("a", "[abc]d"),
    # The `&`, `~` and `|` set-operation characters, which CPython's `translate`
    # escapes and a matcher must treat as ordinary members of a set.
    ("&", "[&]"), ("|", "[|]"), ("~", "[~]"), ("a", "[a&|~]"),
    # A `*` and a bracket together, and `**` in the middle of a pattern.
    ("a/b.py", "*/*.py"), ("a/b/c.py", "*/*/*.py"), ("ab", "a**b"),
    ("axxb", "a**b"), ("axb", "a**b"),
    # Both bracketed and unbracketed names with dots, because a `.` is a plain
    # character in a shell pattern and a program that treats it as a regex
    # wildcard would over-match.
    ("a.py", "*.py"), ("axpy", "a.py"), ("aXb", "a.b"), ("a.b", "a.b"),
]


def CROSS_PAIRS():
    """The pairs CPython answers DIFFERENTLY for `fnmatch` and `pathlib.match`.

    Built by asking CPython rather than written out, because the property being
    asserted is exactly that difference: a pair where the two agree would test
    nothing here, and a hand-written list could rot into agreeing pairs without
    anybody noticing. The `*` is the only thing that can cross a `/` in
    `fnmatch`'s language, so every pair is a pattern with a `/`-reachable `*`.
    """
    names = ["a/b.py", "a/b/c.py", "/a/b", "x/y", "a/", "/", "a//b"]
    pats = ["*", "*.py", "*/*", "?.py", "*/*/*.py", "b*", "[ab]*", "*[ab]",
            "**", "*.PY", "b/*.py", "*/*b*"]
    out = []
    for nm in names:
        for p in pats:
            f = 1 if fnmatch.fnmatch(nm, p) else 0
            q = 1 if pathlib.PurePosixPath(nm).match(p) else 0
            if f != q:
                out.append((nm, p))
    return out


# ── the CPython half ───────────────────────────────────────────────────────

def py_fnmatch(name, pat):
    return "1" if fnmatch.fnmatch(name, pat) else "0"


def py_fnmatchcase(name, pat):
    return "1" if fnmatch.fnmatchcase(name, pat) else "0"


def py_pathlib_match(name, pat):
    return "1" if pathlib.PurePosixPath(name).match(pat) else "0"


# ── the program ────────────────────────────────────────────────────────────

def pair_program(cases, module, extra_import, record):
    """A program for a corpus of PAIRS, carried as one case each.

    The two halves are separated by a TAB inside the case, spelt `~t` in the
    masked corpus — `test_formal_pathlib.py`'s arrangement and for its reason
    (a `~xHH` arm would need a hex-digit reader this module has no reason to
    export). A tab is safe as a separator here and ONLY here: no case in either
    corpus contains one, and `mask` would render a tab as `~t` too, so a corpus
    that ever did would be ambiguous — stated rather than left to be found by a
    length mismatch.

    `record` is one source line with `left_of(s)` and `right_of(s)` in scope.
    """
    return [extra_import, "", "CASES = " + mj(REC.join(
        mask(a.encode("latin-1")) + "~t" + mask(b.encode("latin-1"))
        for a, b in cases) + REC), _UNMASK % {"mod": module}, SPLIT,
        "", "def main():", "    var i = 0", "    var k = 0",
        "    while i < strlen(CASES):",
        "        var j = ndelim(CASES, i)",
        "        var s = unmask(sub(CASES, i, j))", record,
        "        i = j + 2", "        k = k + 1",
        "", "def cut(s) -> int:",
        "    var i = 0",
        "    while i < strlen(s):",
        "        var q: Pointer[UInt8] = s + i",
        "        if q.value() == 9:",
        "            return i",
        "        i = i + 1",
        "    return 0 - 1",
        "",
        "def left_of(s) -> str:",
        "    var c = cut(s)",
        "    var b: Pointer[UInt8] = malloc(c + 1)",
        "    memcpy(b, s, c)",
        "    nul(b, c)",
        "    return b",
        "",
        "def right_of(s) -> str:",
        "    var c = cut(s)",
        "    var n = strlen(s) - c - 1",
        "    var b: Pointer[UInt8] = malloc(n + 1)",
        "    memcpy(b, s + c + 1, n)",
        "    nul(b, n)",
        "    return b",
        "",
        "def nul(out, at) -> int:",
        "    var one: Pointer[UInt8] = malloc(1)",
        "    memset(one, 0, 1)",
        "    memcpy(out + at, one, 1)",
        "    return at + 1",
        ]


# ── the groups ─────────────────────────────────────────────────────────────

def group_resolve(verbose):
    """`fnmatch` binds to this file, and is out of `HOST_MODELLED`.

    Both halves are the same check and they are the reason the entry was
    removed from `formal/imports.py`: a name left in `HOST_MODELLED` after its
    module exists refuses a file that the module could have compiled, which is a
    FALSE statement rather than a conservative one. So the module resolving and
    the entry being gone are one fact, checked together.
    """
    import formal.imports as I
    check("fnmatch" not in I.HOST_MODELLED,
          "fnmatch is still in HOST_MODELLED, so a file importing it is "
          "refused even though formal/hostmods/fnmatch.mojo exists")
    root = os.path.join(HERE, "formal", "hostmods")
    path = I.resolve_module_path("fnmatch", relative_to=os.path.join(root, "x.mojo"),
                                 project_root=root)
    check(path is not None and os.path.isfile(path),
          f"fnmatch does not resolve to a source file (got {path!r})")
    check(os.path.basename(path) == "fnmatch.mojo",
          f"fnmatch resolves to {path!r}, which is not fnmatch.mojo")
    if verbose:
        print(f"    resolves to {os.path.relpath(path, HERE)}, out of "
              f"HOST_MODELLED")
    return True, "resolves to formal/hostmods/fnmatch.mojo, out of HOST_MODELLED"


def group_match(verbose):
    """`fnmatch` and `fnmatchcase` over the corpus, against CPython's both."""
    cases = PAIRS
    record = (f'        printf("%d=%d/%d{REC}{REC}", k, '
              f'fnmatch.fnmatch(left_of(s), right_of(s)), '
              f'fnmatch.fnmatchcase(left_of(s), right_of(s)))')
    got = run(build("\n".join(pair_program(
        cases, "fnmatch", "import fnmatch",
        record)) + "\n", "fm"))
    recs = records(got)
    check(len(recs) == len(cases),
          f"fnmatch: image reported {len(recs)} of {len(cases)}")
    bad = []
    for (idx, ln, v), (a, b) in zip(recs, cases):
        want_f, want_c = py_fnmatch(a, b), py_fnmatchcase(a, b)
        if want_f != want_c:
            bad.append(f"CPython's own two functions disagree on "
                       f"({a!r}, {b!r}): fnmatch {want_f}, fnmatchcase "
                       f"{want_c} — the corpus assumes they are one function on "
                       f"a POSIX target")
        if v != f"{want_f}/{want_c}":
            bad.append(f"({a!r}, {b!r}): image {v}, CPython "
                       f"{want_f}/{want_c}")
    check(not bad, f"fnmatch: {len(bad)} of {len(cases)} differ; first: "
                   + (bad[0] if bad else ""))
    if verbose:
        print(f"    {len(cases)} pairs: the brackets, the ranges, the "
              f"unterminated `[`, and both spellings")
    return True, f"{len(cases)} fnmatch/fnmatchcase answers agree with CPython"


def group_cross(verbose):
    """The pairs where `fnmatch` and `pathlib.match` must DISAGREE.

    The corpus is built by asking CPython for pairs it answers differently (see
    `CROSS_PAIRS`), so every case here is a pair where the `cross` flag is the
    only thing that can produce the right answer.
    """
    cases = CROSS_PAIRS()
    check(len(cases) >= 12,
          f"only {len(cases)} pairs where CPython's fnmatch and pathlib.match "
          f"disagree; the corpus is too small to pin the flag")
    # `import pathlib` and a dotted call, NOT `from pathlib import match as
    # pmatch`: a from-import ALIAS is not honoured for a call into another
    # image (FORMAL_from_import_alias_dangles_the_call), which is a
    # refusal naming a name rather than a wrong answer, and the first version of
    # this group spelled it that way.
    record = (f'        printf("%d=%d/%d{REC}{REC}", k, '
              f'fnmatch.fnmatch(left_of(s), right_of(s)), '
              f'pathlib.match(left_of(s), right_of(s)))')
    got = run(build("\n".join(pair_program(
        cases, "fnmatch", "import fnmatch\nimport pathlib",
        record)) + "\n", "cross"))
    recs = records(got)
    check(len(recs) == len(cases),
          f"cross: image reported {len(recs)} of {len(cases)}")
    bad = [(a, b, v, f"{py_fnmatch(a, b)}/{py_pathlib_match(a, b)}")
           for (idx, ln, v), (a, b) in zip(recs, cases)
           if v != f"{py_fnmatch(a, b)}/{py_pathlib_match(a, b)}"]
    check(not bad, f"cross: {len(bad)} of {len(cases)} differ from CPython; "
                   f"first: " + (f"({bad[0][0]!r}, {bad[0][1]!r}) image "
                                 f"{bad[0][2]}, CPython {bad[0][3]}"
                                 if bad else ""))
    if verbose:
        print(f"    {len(cases)} pairs CPython answers differently for the two "
              f"functions")
    return True, (f"{len(cases)} pairs separate fnmatch's `*` from "
                  f"pathlib.match's, both as CPython answers them")


GROUPS = {"resolve": group_resolve, "match": group_match,
          "cross": group_cross}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        TEMP = tmp
        J.TEMP = tmp          # `build`/`run` are imported, and read J's own
        for n in names:
            total += 1
            try:
                _, detail = GROUPS[n](args.verbose)
                print(f"PASS {n:10s} {detail}")
            except Failure as e:
                print(f"FAIL {n:10s} {e}")
                failed.append(n)
    print(f"\n{total - len(failed)}/{total} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())