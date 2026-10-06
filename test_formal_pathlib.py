#!/usr/bin/env python3
"""Build `pathlib` for the formal backend and RUN it, compared with CPython.

    python3 test_formal_pathlib.py [-v] [group ...]

Why an oracle rather than a table. Every case is computed twice — once through
`python3 fire.py build --formal --no-prove` and executed, once through
`pathlib` in this process — and the two have to agree. Nothing here states
what `PurePosixPath("a/b/").name` is; it asks. Path answers are short, which
is exactly what makes a table of them dangerous: `name`, `stem` and `suffix`
differ from each other by one rule each, and a table of expected values with a
transposed row looks like a pass.

The corpus and the record plumbing are IMPORTED from `test_formal_json.py`
rather than copied — the mask, the unmask, the record parser and the
comparison — because a second copy of the mask is a second spelling of "a
byte a source literal cannot hold", and the first version of `json`'s mask had
a bug in it that a copy would have inherited silently.

Groups: `resolve`, `decompose`, `rewrite`, `relative`, `match`, `reserved`,
`absent`. With no argument, all.
"""
import argparse
import os
import pathlib
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

from test_formal_json import (Failure, build, check, corpus_const,  # noqa: E402
                              mask, mj, records, run, REC)
import test_formal_json as J  # noqa: E402

TEMP = None

# The unmask, with the module it asks for filled in. The two host modules
# export the byte helpers under their own names (`json.byte_at` /
# `pathlib.byte_or`) and the mask cannot tell which module it is building an
# input for, so the name is a parameter rather than a second copy.
# `byte_at` becomes `byte_or` as well as taking the module's name: the two
# host modules spell the bounded byte read differently, and a substitution that
# only swapped the module would have produced a call to a name this one does
# not export — which the build reports as precisely that.
_UNMASK = J.UNMASK.replace("json.byte_at", "%(mod)s.byte_or")
_UNMASK = _UNMASK.replace("json.", "%(mod)s.")
# `hexdig` is `json`'s, and the `~xHH` form is the only mask form that needs
# it. NO case in this file's corpora uses one — they are all printable paths
# and patterns — so the arm is REPLACED rather than given a second home, and
# what it writes is a NUL so that a corpus which did use the form would
# truncate and fail loudly instead of decoding to something plausible. The
# tab separator `pair_program` uses is `~t` precisely so that this is never
# reached.
_UNMASK = _UNMASK.replace(
    """        else:
            var h = 16 * %(mod)s.hexdig(%(mod)s.byte_or(t, i + 2)) + %(mod)s.hexdig(%(mod)s.byte_or(t, i + 3))
            u = %(mod)s.put_byte(out, u, h)
            i = i + 4""",
    """        else:
            u = %(mod)s.put_byte(out, u, 0)
            i = i + 4""")


def unmask(mod):
    return _UNMASK % {"mod": mod}


SPLIT = J.SPLIT.replace("json.byte_at", "pathlib.byte_or")
SPLIT = SPLIT.replace("json.", "pathlib.")


# ── the corpora ────────────────────────────────────────────────────────────
#
# Written for SHAPES. Every awkward corner of a POSIX path grammar is in the
# first group: the root, a trailing separator, doubled and dotted separators,
# a leading `//`, a `..` that must SURVIVE normalisation, a name that is only
# dots, and a name that is nothing but a dot.

DECOMPOSE = [
    "", "/", "//", "///", "a", "a/b", "a/b/", "a//b", "a/./b", "a/../b",
    "/a/b/", "x.tar.gz", ".hidden", "a/.hidden", "a.", "a..", "..", "../..",
    "a/b/c.tar", "a b/c d", "a/b/c/d/e", "/x", "x/", "./a", "a/b/..", "//a",
    "a/b/c.tar.gz", "/x/y.z", "a.b.c.d", "...", ".", "..a", "a..b",
    "a/b.c", "/a.b/c.d/e", "a//b//c//", "1/2/3.4.5", "-", "a-b-c",
    "/usr/local/lib/libpython3.14.dylib", "a/b/", "x.", ".x.",
]

REWRITE_SUFFIX = ["", ".json", ".tar.gz", "x", ".x/y", "/", ".a.b", "."]
REWRITE_NAME = ["", "x", "y.z", "a/b"]
REWRITE_STEM = ["", "x", "y"]

RELATIVE = [
    ("/a/b/c", "/a"), ("a/b", "a"), ("a/b", "/a"), ("a/b", "a/b"),
    ("a", "a/b"), ("a/b/c", "a/b"), ("a/./b", "a"), ("a/b", "b"),
    ("a/b", "a/"), ("a/b/", "a"), ("a//b", "a"), ("", ""), ("a", ""),
    ("", "a"), ("/a", "/a"), ("/a/b", "/a/b/c"), ("a/b/c", "c"),
    ("x/y.tar.gz", "x"), ("./a/b", "a"), ("a/b/..", "a"),
]

MATCHES = [
    ("a/b.py", "*.py"), ("a/b.py", "b.py"), ("a/b.py", "/*.py"),
    ("b.py", "*.py"), ("a/b/c.py", "b/*.py"), ("a/b", "b"),
    ("a/b.py", "?.py"), ("a/b/c.py", "*.py"), ("a/b.py", "a/*.py"),
    ("a/b/c.py", "a/b/*.py"), ("a/b/c.py", "a/*.py"), ("a/b.py", "*"),
    ("a/b.py", "*/*"), ("a/b.py", "b*"), ("a/b.py", "*.PY"),
    ("a/b.py", "[ab].py"), ("a/b.py", "[!ab].py"), ("a/b.py", "[^ab].py"),
    ("a/b.py", "[a-c].py"), ("a/b.py", "[]]"), ("a/b.py", "[!]]"),
    ("a/b.py", "[abc"), ("a/b.py", "b[.]py"), ("a/b/c.py", "**/*.py"),
    ("a/b/c.py", "**/c.py"), ("a/b/c.py", "**"), ("a/b/c.py", "a/**"),
    ("a/b/c.py", "a**"), ("a.py", "*.py"), ("a/b", "a/b"),
    ("", "*"), ("", ""), ("a", ""), ("a", "a"), ("a", "A"),
    ("/a/b", "/b"), ("/a/b", "/a/b"), ("/a/b.py", "/*.py"), ("/a/b.py", "a/*.py"),
    ("/x", "/x"), ("a", "/a"), ("/", "/"), ("/a", "/a/*"),
    # The `**` patterns whose answers are the argument for treating `**` as
    # `*` in this walk; the module docstring quotes all thirteen.
    ("a/b", "a/**"), ("a", "a/**"), ("a/b/c/d", "a/**/d"), ("a/b/c", "a/**/c"),
    ("a/b/c.py", "a/**/c.py"), ("a", "**"),
    # A path with no components, which `as_posix` spells ".".
    ("/", "*"), (".", "*"), ("", "a"), ("a/..", "*"),
    ("dir/f.txt", "*.txt"), ("dir/sub/f.txt", "dir/*.txt"),
    ("a/b/c/d.tar.gz", "*.gz"), ("a/b/c", "**/c"), ("x", "**/x"),
    # An unterminated `[` is a LITERAL `[`, and a `-` immediately before the
    # closing `]` is a literal `-` rather than half a range. Both were answered
    # 0 here before the matcher moved to `formal/hostmods/fnmatch.mojo` — the
    # walk ran past the end of the set and then called it unterminated — and
    # both are in this corpus because the corpus is what noticed.
    ("a[", "a["), ("[", "["), ("a[b", "a[b"), ("a", "a["), ("[abc", "[abc"),
    ("[a", "[a"), ("a.b", "a["), ("[", "[!"), ("-", "[a-]"), ("a-", "[a-]"),
    ("-", "[--0]"), ("b", "[a-]b"), ("-", "[a-c-]"), ("a", "[!a-]"),
]


# ── the CPython half ───────────────────────────────────────────────────────

def P(s):
    return pathlib.PurePosixPath(s)


def py_as_posix(s):
    return P(s).as_posix()


def py_name(s):
    return P(s).name


def py_stem(s):
    return P(s).stem


def py_suffix(s):
    return P(s).suffix


def py_parent(s):
    return P(s).parent.as_posix()


def py_with_name(s, n):
    try:
        return P(s).with_name(n).as_posix()
    except ValueError:
        return py_as_posix(s)


def py_with_stem(s, n):
    try:
        return P(s).with_stem(n).as_posix()
    except ValueError:
        return py_as_posix(s)


def py_with_suffix(s, x):
    try:
        return P(s).with_suffix(x).as_posix()
    except ValueError:
        return py_as_posix(s)


def py_relative_to(a, b):
    try:
        return P(a).relative_to(b).as_posix()
    except ValueError:
        return ""


def py_match(a, b):
    # CPython RAISES on an empty pattern and this path has no exceptions, so
    # the module answers 0 for one and says so at `match`; the oracle here has
    # to agree, and the corpus keeps the case because "an empty pattern is 0"
    # is a claim worth checking rather than worth omitting.
    if b == "":
        return "0"
    return "1" if P(a).match(b) else "0"


def py_reserved(s):
    return "1" if P(s).is_reserved() else "0"


# ── the program builder ────────────────────────────────────────────────────

def corpus_program(cases, body):
    """A program that walks `cases` and runs `body` on each.

    `body` is a list of source lines with `s` in scope — the unmasked case —
    and it emits records. Every single-argument group is this plus its own
    `body`, so the driver exists once.
    """
    return ["import pathlib", "",
            corpus_const([c.encode("latin-1") for c in cases]),
            unmask("pathlib"), SPLIT,
            "", "def main():", "    var i = 0", "    var k = 0",
            "    while i < strlen(CASES):",
            "        var j = ndelim(CASES, i)",
            "        var s = unmask(sub(CASES, i, j))"] + body + [
            "        i = j + 2", "        k = k + 1"]


def pair_program(cases, record):
    """A program for a corpus of PAIRS, carried as one case each.

    The two halves are separated by a TAB inside the case, spelt `~t` in the
    masked corpus. A tab and not `~x01` because the `~xHH` arm of the unmask is
    the one that needs a hex digit reader, and `pathlib` has no reason to
    export one — the first version of this used `~x01` and the arm had been
    stubbed to write a NUL, which truncated the case and took the image down
    with it. A tab is safe as a separator here and ONLY here: no case in this
    file contains one, and `mask` would render a tab as `~t` too, so a corpus
    that ever did would be ambiguous — stated rather than left to be found by
    a length mismatch.

    `record` is one source line with `left_of(s)` and `right_of(s)` in scope.
    """
    return ["import pathlib", "", "CASES = " + mj(REC.join(
        mask(a.encode("latin-1")) + "~t" + mask(b.encode("latin-1"))
        for a, b in cases) + REC), unmask("pathlib"), SPLIT,
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
        "    return at + 1"]


def emit_str(idx, value):
    return f'        printf("%d:%s{REC}", strlen({value}), {value}, "{REC}")'


def emit_int(idx, value):
    """One `k=value` record for an INTEGER read.

    `k` and the value are BOTH arguments: a format with two `%d` and one
    argument reads whatever register the second one lands in, which is how the
    first version of the `reserved` group reported a pointer where an answer
    should have been.
    """
    return f'        printf("%d=%d{REC}", k, {value}, "{REC}")'


# ── group: resolve ─────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import pathlib` finds this file, and the name left `HOST_MODELLED`.

    The same two claims `test_formal_json.py`'s `resolve` group makes, for the
    same reason: `HOST_MODELLED` says a module COULD be written, and a name
    leaves it by being written, because an entry left behind would refuse a
    file after the module that answers it is sitting in the tree.
    """
    check(os.path.isfile(os.path.join(HERE, "formal", "hostmods",
                                      "pathlib.mojo")),
          "no Mojo source for pathlib in formal/hostmods/")
    import formal.imports as I
    got = I.resolve_module_path("pathlib")
    check(got is not None
          and os.path.samefile(
              got, os.path.join(HERE, "formal", "hostmods", "pathlib.mojo")),
          f"import pathlib resolves to {got!r}")
    check(I.host_module_tier("pathlib") == "",
          "pathlib is still in HOST_MODELLED; its Mojo source exists, so the "
          "entry is now a false statement about the target")
    for stray in ("pathlib.mojo",):
        check(not os.path.isfile(os.path.join(HERE, stray)),
              f"{stray} is at the repository root, which four independent "
              f"resolvers search")
    if verbose:
        print(f"    import pathlib -> {os.path.relpath(got, HERE)}")
    return True, f"resolves to {os.path.relpath(got, HERE)}, out of HOST_MODELLED"


def group_decompose(tmpdir, verbose):
    """`as_posix`, `name`, `stem`, `suffix`, `parent`, over the whole corpus.

    FIVE reads per path and ONE program, because the reads are the same walk
    over the same string and a program that did them separately would be five
    builds for the same answer. The corpus is the shapes: the root, a trailing
    separator, doubled and dotted separators, a leading `//`, a `..` that has
    to survive, a name that is only dots, and a leading dot that is part of the
    name rather than the start of a suffix.
    """
    cases = DECOMPOSE
    body = []
    for fn, want in (("as_posix", py_as_posix), ("name", py_name),
                     ("stem", py_stem), ("suffix", py_suffix),
                     ("parent", py_parent)):
        body.append(emit_str(0, f'pathlib.{fn}(s)'))
    got = run(build("\n".join(corpus_program(cases, body)) + "\n", "decompose"))
    recs = records(got)
    check(len(recs) == len(cases) * 5,
          f"decompose: image reported {len(recs)} of {len(cases) * 5} reads")
    bad = []
    # The program emitted all of one reader, then all of the next, so the
    # readers are the record list strided by five.
    for fn, want, col in (("as_posix", py_as_posix, 0), ("name", py_name, 1),
                          ("stem", py_stem, 2), ("suffix", py_suffix, 3),
                          ("parent", py_parent, 4)):
        for (idx, ln, val), c in zip(recs[col::5], cases):
            if val != want(c):
                bad.append((fn, c, val, want(c)))
    check(not bad, f"decompose: {len(bad)} read(s) differ from CPython; first: "
                   + (f"{bad[0][0]}({bad[0][1]!r}) image {bad[0][2]!r} "
                      f"CPython {bad[0][3]!r}" if bad else ""))
    if verbose:
        print(f"    {len(cases)} paths x 5 reads")
    return True, f"{len(cases)} x 5 decomposition reads agree with CPython"


def group_rewrite(tmpdir, verbose):
    """`with_name`, `with_stem` and `with_suffix`, over a corpus of ARGUMENTS.

    Three programs, one per function, each over the whole path corpus with one
    argument held fixed — the argument is a second string, so a corpus has to
    carry both and one program per argument would be 40 builds for the same
    answer.

    `with_suffix`'s argument corpus is the one that matters: a suffix, an EMPTY
    suffix (which REMOVES one, and is what `tools/ab_filelist.py` uses), a
    name that is not a suffix at all, a suffix with a separator in it, and a
    two-part suffix. The first two are the spellings a ported program writes
    and the last three are the ones CPython raises on.
    """
    bad = []
    n = 0
    for fn, args, want in (
            ("with_name", REWRITE_NAME, py_with_name),
            ("with_stem", REWRITE_STEM, py_with_stem),
            ("with_suffix", REWRITE_SUFFIX, py_with_suffix)):
        for a in args:
            cases = [(p, a) for p in DECOMPOSE]
            call = f'pathlib.{fn}(left_of(s), right_of(s))'
            record = (f'        printf("%d:%s{REC}", strlen({call}), {call}, '
                      f'"{REC}")')
            got = run(build("\n".join(
                pair_program(cases, record)) + "\n", f"rw_{fn}_{len(a)}"))
            recs = records(got)
            check(len(recs) == len(cases),
                  f"{fn}(*{a!r}): image reported {len(recs)} of {len(cases)}")
            for (idx, ln, val), (p, aa) in zip(recs, cases):
                n += 1
                w = want(p, aa)
                if val != w:
                    bad.append((fn, p, aa, val, w))
    check(not bad, f"rewrite: {len(bad)} rewrite(s) differ from CPython; "
                   "first: " + (f"{bad[0][0]}({bad[0][1]!r}, {bad[0][2]!r}) "
                                f"image {bad[0][3]!r} CPython {bad[0][4]!r}"
                                if bad else ""))
    if verbose:
        print(f"    {n} rewrites over 3 functions x 3 argument corpora")
    return True, f"{n} rewrites agree with CPython"


def group_relative(tmpdir, verbose):
    """`relative_to` over a corpus of PAIRS, compared with CPython's own.

    Half the corpus is pairs CPython REFUSES, and those are the half that
    matters: the sentinel this module returns has to be distinguishable from
    every value CPython's own `relative_to` can produce, or a caller cannot
    act on it. `""` is such a value — `relative_to(x, x)` is `"."` — and
    `py_relative_to` says so by returning `""` exactly where CPython raises.
    """
    cases = RELATIVE
    call = 'pathlib.relative_to(left_of(s), right_of(s))'
    record = (f'        printf("%d:%s{REC}", strlen({call}), {call}, "{REC}")')
    got = run(build("\n".join(pair_program(cases, record)) + "\n",
                    "relative"))
    recs = records(got)
    check(len(recs) == len(cases),
          f"relative_to: image reported {len(recs)} of {len(cases)}")
    bad = [(a, b, v, py_relative_to(a, b))
           for (idx, ln, v), (a, b) in zip(recs, cases)
           if v != py_relative_to(a, b)]
    check(not bad, f"relative_to: {len(bad)} differ from CPython; first: "
                   + (f"({bad[0][0]!r}, {bad[0][1]!r}) image {bad[0][2]!r} "
                      f"CPython {bad[0][3]!r}" if bad else ""))
    if verbose:
        print(f"    {len(cases)} pairs, including the not-under cases")
    return True, f"{len(cases)} relative_to answers agree with CPython"


def group_match(tmpdir, verbose):
    """`match` over a corpus of PAIRS, against CPython's own.

    The corpus is the two RULES and the pattern language. Right alignment:
    three patterns that say nothing at all about the leading component, which
    is what `fnmatch` would get wrong. Anchoring: one pattern starting with
    `/`, which must match the whole path. `**` as a COMPONENT rather than a
    recursive `*`. And the bracket forms: a set, two spellings of negation, a
    range, `]` as a literal, and an unterminated `[` that is a literal too.
    """
    cases = MATCHES
    call = 'pathlib.match(left_of(s), right_of(s))'
    record = f'        printf("%d=%d{REC}", k, {call}, "{REC}")'
    got = run(build("\n".join(pair_program(cases, record)) + "\n", "match"))
    recs = records(got)
    check(len(recs) == len(cases),
          f"match: image reported {len(recs)} of {len(cases)}")
    bad = [(a, b, v, py_match(a, b))
           for (idx, ln, v), (a, b) in zip(recs, cases) if v != py_match(a, b)]
    check(not bad, f"match: {len(bad)} differ from CPython; first: "
                   + (f"match({bad[0][0]!r}, {bad[0][1]!r}) image {bad[0][2]} "
                      f"CPython {bad[0][3]}" if bad else ""))
    if verbose:
        print(f"    {len(cases)} pairs, both alignment rules and the brackets")
    return True, f"{len(cases)} match answers agree with CPython"


def group_reserved(tmpdir, verbose):
    """`is_reserved`, over a corpus that includes the names it is FOR.

    On POSIX the answer is 0 for everything, and the corpus says so by
    including `CON`, `NUL` and `PRN` — the three that are the whole reason
    the function exists and the three for which a copy that answered 1 would
    be a wrong answer rather than a missing one.
    """
    cases = ["", "a", "a/b", "con", "CON", "NUL", "PRN", "COM1", "LPT1",
             "a:b", "a b", "/con", "con.txt", "x/CON"]
    body = [emit_int(0, "pathlib.is_reserved(s)")]
    got = run(build("\n".join(corpus_program(cases, body)) + "\n", "reserved"))
    recs = records(got)
    check(len(recs) == len(cases),
          f"is_reserved: image reported {len(recs)} of {len(cases)}")
    bad = [(c, v, py_reserved(c)) for (idx, ln, v), c in zip(recs, cases)
           if v != py_reserved(c)]
    check(not bad, f"is_reserved: {len(bad)} differ from CPython; first: "
                   + (f"{bad[0][0]!r} image {bad[0][1]} CPython {bad[0][2]}"
                      if bad else ""))
    if verbose:
        print(f"    {len(cases)} paths, including CON/NUL/PRN")
    return True, f"{len(cases)} is_reserved answers agree with CPython"


def group_absent(tmpdir, verbose):
    """The names this module does NOT have, asserted as refusals.

    Each is a CPython `pathlib` name with no representation here — a type, a
    sequence, the filesystem half — and the module docstring says which
    capability each one needs. An omission that is not pinned is
    indistinguishable from an implementation, so each is pinned as a build
    that fails with a message naming the module and the name.
    """
    absent = ["Path", "PurePath", "PurePosixPath", "PosixPath", "parts",
              "parents", "suffixes", "is_absolute", "joinpath", "iterdir",
              "rglob", "glob", "stat", "read_text", "write_text", "resolve",
              "cwd", "unlink", "mkdir", "touch", "as_uri", "drive", "root",
              "anchor"]
    for name in absent:
        src = ("import pathlib\n\ndef main() -> int:\n"
               f"  pathlib.{name}()\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"pathlib.{name}() built, but the module documents it as absent "
              f"— either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"pathlib.{name}() failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


GROUPS = {
    "resolve": group_resolve,
    "decompose": group_decompose,
    "rewrite": group_rewrite,
    "relative": group_relative,
    "match": group_match,
    "reserved": group_reserved,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        J.TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                import traceback
                if args.verbose:
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
