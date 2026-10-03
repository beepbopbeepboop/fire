#!/usr/bin/env python3
"""Build `os` and `os.path` for the formal backend and RUN them, against
CPython's own answers.

    python3 test_formal_os.py [-v] [group ...]

Why an oracle rather than a table of expected strings. `os.path` here is a
transcription of CPython's `posixpath`/`genericpath` — `dirname`, `basename`,
`split`, `splitext`, `normpath`, `join`, `relpath` — and a transcription is
exactly the kind of thing that is right on the inputs you tried and wrong on
the one you did not. So every case below is run TWICE: once through
`python3 fire.py build --formal --no-prove` and executed, and once through the
`posixpath` in this process, and the two answers have to be equal. Nothing in
this file states what `dirname("a/b/")` is; it asks.

The same argument applies to the filesystem half, with the oracle being the
real filesystem: the program under test creates, renames, chmods and removes a
fixture tree, and the assertions are made afterwards by `os.path.exists`,
`os.stat` and friends in this process. A module that computed a plausible
number instead of doing the operation cannot pass that.

Building and RUNNING, not building. `test_formal.py` typechecks the generated
proof and never executes the image, and an entire class of Mach-O emission bug
can be green there; every case here exits with a status this file checks.

Groups: `strings`, `posixpath`, `fs`, `env`, `dirs`. With no argument, all of
them. `posixpath` is the `strings` corpus and the same oracle under CPython's
other name for the same module, which is what a re-export needs to be measured
rather than assumed.
"""
import argparse
import os
import posixpath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

# The strings every path case is run over. Chosen for the shapes rather than
# for the words: an empty path, a bare name, one separator, two adjacent
# separators, a trailing separator, a leading separator, a doubled leading
# separator (which CPython's `split` treats as significant and a naive
# transcription does not), a dot file, a leading run of dots, a name that is
# only dots, a `.` component, a `..` component, a `..` that has nothing to pop,
# and a path with an extension in a directory component rather than in the
# name.
STRINGS = [
    "", "a", "a/b", "a/b/c", "/", "//", "///", "/a", "//a", "a/", "a//",
    "a/b/", "a/./b", "a/../b", "a/b/..", "a/..", "..", ".", "./", "../..",
    "a/b/c.txt", "a.b/c", "/a/b/", "x/y.tar.gz", "...", "..a", "a..b",
    "a/b.c/d", "dir.d/file", "a b/c d", "-", "a/-",
]

# (label, the call with one %s, the CPython answer as a tuple, "s" or "i")
#
# `s` prints the value as a string and compares it with `[%s]`; `i` prints it
# as an integer, which is what a predicate has to be compared as — `printf`
# with `%s` on a word prints a pointer, and a test that used it would be
# comparing addresses.
ONE_ARG_CASES = [
    ("dirname", "dirname(%s)", lambda a: (posixpath.dirname(a),), "s"),
    ("basename", "basename(%s)", lambda a: (posixpath.basename(a),), "s"),
    ("split", "split(%s)", lambda a: posixpath.split(a), "s"),
    ("splitext", "splitext(%s)", lambda a: posixpath.splitext(a), "s"),
    ("normpath", "normpath(%s)", lambda a: (posixpath.normpath(a),), "s"),
    ("isabs", "isabs(%s)", lambda a: (int(posixpath.isabs(a)),), "i"),
    ("splitdrive", "splitdrive(%s)", lambda a: posixpath.splitdrive(a), "s"),
]


def commonprefix2(a, b):
    """`posixpath.commonprefix` over TWO strings.

    CPython only exposes it for a list, and this module takes two arguments —
    a variadic `*paths` is refused on this path, and a list would need a
    length known at build time. This is CPython's own body, transcribed:

        s1 = min(m)
        for i, c in enumerate(s1):
            if c != m[i][i]:
                return s1[:i]
        return s1

    which is a character-wise comparison, NOT a path-component one — so
    `commonprefix("a/b", "a/c")` is `"a/"` and not `"a"`, and the test asserts
    the module agrees about that too.
    """
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return a[:i]
    return a[:n]


# Where CPython RAISES and this module has no exception to raise, the answer it
# gives instead is pinned here rather than left in a docstring — a documented
# deviation that nothing checks is a claim, and this is the only one in the
# module. `posixpath.relpath("")` is a `ValueError`; here an empty `path` is
# the working directory, so `relpath("", "a")` is `".."`, which is what
# `relpath` says when the two paths are the same one and one is below the
# other. There is no `try`/`except` on this path at all (FORMAL.md phase 7).
DEVIATION_CASES = [
    ("relpath-empty", 'relpath("", "a")', ".."),
]


# The two-argument functions, each with its own set of pairs.
#
# `join` is run over a cross product rather than over one list, because the
# interesting behaviour is in the INTERACTION: an absolute second component
# discards the first, an empty first component contributes no separator, and a
# trailing separator on the first is not doubled. One list of hand-picked pairs
# would miss the case where the two halves come from different rules.
JOIN_SECONDS = ["", "b", "b/c", "/abs", ".", "..", "a/", "a//", "a/./b",
                "a/../b", "b.c", "/", "x/"]
JOIN_FIRSTS = ["a", "a/b", "/a", "", ".", "a/", "/"]

RELPAIRS = [("a/b/c", "a"), ("a/b/c", "/a"), ("/a/b", "/a/b/c"), ("/a", "/a"),
            (".", "a/b"), ("a", "a"), ("a/..", "a/b"), ("/a/b/../c", "/a"),
            ("/x/y/z", "/x"), ("x", "/"), ("a//b", "/a//b"),
            ("a/b", ""), (".", "."), ("/", "/")]

PREFIX_PAIRS = [("abcd", "abcd"), ("abcd", "abxx"), ("abxx", "abcd"),
                ("a/b", "a/c"), ("", "x"), ("x", ""), ("", ""),
                ("/a/b", "/a/c"), ("abc", "ab"), ("ab", "abc")]

TWO_ARG_CASES = [
    ("join", "join(%s, %s)", posixpath.join,
     [(a, b) for a in JOIN_FIRSTS for b in JOIN_SECONDS]),
    ("relpath", "relpath(%s, %s)", posixpath.relpath, RELPAIRS),
    ("commonprefix", "commonprefix(%s, %s)", commonprefix2, PREFIX_PAIRS),
]


def mojo_string(s):
    """A Mojo string literal for `s`.

    The four escapes a path can contain that a Mojo literal has to spell, and
    nothing else: a fixture path with a quote or a backslash in it would
    otherwise be a source-level difference between the two runs, which is the
    kind of difference an oracle must not have.
    """
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + out + '"'


# The record terminator. NOT a newline, and for a reason that does not expire:
# a separator this suite can read back WITHOUT asking whether the image decoded
# a literal. `@@` is two bytes that a real newline cannot collide with, so every
# program in this file emits its records back to back and this token is what
# separates them. The `printf` string-escape question behind the old wording is
# recorded in `bugs/FORMAL_pointer_value_model.md`, and `test_formal_run.py`'s
# harness cases avoid line-structured output for the same reason.
REC = "@@"


def emit_case(label, ai, call, kind, nparts):
    """The lines of Mojo that evaluate one case and print it.

    The printed form is `label|argindex|partindex|value` followed by `REC`, with
    a string value wrapped in `[...]` so that an empty one is visible and a
    value containing a `|` cannot be confused with two fields.
    """
    if nparts == 1:
        body = [f"    r = {call}"]
        fmt = "[%s]" if kind == "s" else "%d"
        body.append(f'    printf("{label}|{ai}|0|{fmt}{REC}", r)')
    else:
        body = [f"    p0, p1 = {call}"]
        for k in (0, 1):
            body.append(f'    printf("{label}|{ai}|{k}|[%s]{REC}", p{k})')
    return body


def render(values, kind):
    return f"[{values}]" if kind == "s" else str(values)


def build_strings_program(module="os.path"):
    """The whole `strings` group as one program, plus the expected output.

    One program rather than one per case: the module is compiled once, so a
    hundred cases cost one build, and a failure in the module is reported once
    with its message instead of a hundred times as a timeout.

    `module` is the SPELLING the program imports from, and the only thing it
    changes: the corpus, the emitted calls and every expected answer are the
    same, and the oracle is this process's own `posixpath` either way. That is
    what makes the `posixpath` group a measurement of the RE-EXPORT rather than a
    second copy of the corpus — see `group_posixpath`.
    """
    imports = sorted({c[1].split("(")[0] for c in ONE_ARG_CASES}
                     | {c[0] for c in TWO_ARG_CASES})
    lines = [f"from {module} import " + ", ".join(imports), "",
             "def main(n):"]
    expected = []
    for label, tmpl, py, kind in ONE_ARG_CASES:
        for ai, a in enumerate(STRINGS):
            want = py(a)
            lines += emit_case(label, ai, tmpl % mojo_string(a), kind, len(want))
            for k, v in enumerate(want):
                expected.append(f"{label}|{ai}|{k}|{render(v, kind)}")
    for label, tmpl, py, pairs in TWO_ARG_CASES:
        for ai, (a, b) in enumerate(pairs):
            want = (py(a, b),)
            lines += emit_case(label, ai, tmpl % (mojo_string(a),
                                                  mojo_string(b)), "s", 1)
            expected.append(f"{label}|{ai}|0|[{want[0]}]")
    for label, call, want in DEVIATION_CASES:
        lines += emit_case(label, 0, call, "s", 1)
        expected.append(f"{label}|0|0|[{want}]")
    lines.append("    return 0")
    return "\n".join(lines) + "\n", expected


FS_PROGRAM = """\
from os import getcwd, chdir, makedirs, mkdir, rmdir, remove, unlink
from os import rename, replace, chmod, getenv, putenv, unsetenv
from os.path import exists, isfile, isdir, getsize, join, abspath, realpath
from os.path import relpath, expanduser

# One record per fact, so that a key never contains a space: the harness
# splits a record on its first space and a key with one in it would be
# mis-parsed rather than mis-compared.
def show(tag, p):
    printf("%s-exists=%d@@", tag, exists(p))
    printf("%s-isfile=%d@@", tag, isfile(p))
    printf("%s-isdir=%d@@", tag, isdir(p))

def main(n):
    root = {root}
    # ── the four predicates, on the four shapes a path can have ──
    show("file", join(root, "f.txt"))
    show("dir", join(root, "d"))
    show("missing", join(root, "nope"))
    show("under-missing", join(root, "nope/deeper"))
    printf("size=%d@@", getsize(join(root, "f.txt")))
    printf("size-missing=%d@@", getsize(join(root, "nope")))
    # ── making and removing directories ──
    printf("mkdir=%d@@", mkdir(join(root, "one"), 511))
    printf("mkdir-again=%d@@", mkdir(join(root, "one"), 511))
    printf("makedirs=%d@@", makedirs(join(root, "a/b/c"), 511))
    show("made", join(root, "a/b/c"))
    printf("makedirs-again=%d@@", makedirs(join(root, "a/b/c"), 511))
    printf("makedirs-deep=%d@@", makedirs(join(root, "a/b/c/d/e"), 511))
    printf("makedirs-kept=%d@@", makedirs(join(root, "p/q/r"), 511))
    show("made-deep", join(root, "p/q/r"))
    printf("rmdir=%d@@", rmdir(join(root, "a/b/c/d/e")))
    show("removed", join(root, "a/b/c/d/e"))
    printf("rmdir-missing=%d@@", rmdir(join(root, "a/b/c/d/e")))
    # A second deep tree, which is NOT removed: the checks above run before
    # the rmdir, so nothing this process can ask afterwards would confirm
    # them. Every path the oracle checks after the run is one the program
    # leaves behind.
    printf("remove=%d@@", remove(join(root, "f.txt")))
    show("removed-file", join(root, "f.txt"))
    printf("remove-again=%d@@", remove(join(root, "f.txt")))
    # ── renaming, and the atomic-overwrite spelling ──
    # `rename` and `replace` each get their own pair, and neither the source
    # nor the destination of a `replace` is touched again afterwards, so the
    # state the program leaves is the state the oracle can check.
    printf("touch=%d@@", write_file(join(root, "x1")))
    printf("rename=%d@@", rename(join(root, "x1"), join(root, "x2")))
    show("gone", join(root, "x1"))
    # A second rename whose result is never touched again, so that the state
    # the program LEAVES is the state this process can check afterwards. A
    # check made mid-program and a check made after it are different
    # assertions, and only the second one can have a real filesystem behind it.
    printf("touch4=%d@@", write_file(join(root, "z1")))
    printf("rename2=%d@@", rename(join(root, "z1"), join(root, "z2")))
    show("renamed", join(root, "z2"))
    show("gone2", join(root, "z1"))
    printf("touch2=%d@@", write_file(join(root, "y1")))
    printf("touch3=%d@@", write_file(join(root, "y2")))
    printf("replace=%d@@", replace(join(root, "y1"), join(root, "y2")))
    show("replaced-away", join(root, "y1"))
    show("replaced", join(root, "y2"))
    printf("unlink=%d@@", unlink(join(root, "x2")))
    show("unlinked", join(root, "x2"))
    printf("unlinked-size=%d@@", getsize(join(root, "x2")))
    # ── permissions, checked by the caller with os.stat ──
    printf("chmod=%d@@", chmod(join(root, "perm"), 384))
    printf("chmod-missing=%d@@", chmod(join(root, "no-such"), 384))
    # ── the working directory, and coming back from it ──
    printf("cwd-rel=[%s]@@", relpath(join(root, "a"), getcwd()))
    printf("chdir=%d@@", chdir(join(root, "a")))
    printf("cwd-in=%s@@", getcwd())
    printf("chdir-back=%d@@", chdir(root))
    printf("chdir-missing=%d@@", chdir(join(root, "nope")))
    # ── abspath and realpath of a path that is already absolute ──
    printf("abspath=%s@@", abspath("/x/./y/../z"))
    printf("realpath=%s@@", realpath("/"))
    # `expanduser`, against `$HOME`.
    printf("expanduser-tilde=[%s]@@", expanduser("~"))
    printf("expanduser-slash=[%s]@@", expanduser("~/sub"))
    printf("expanduser-other=[%s]@@", expanduser("~someone/sub"))
    printf("expanduser-abs=[%s]@@", expanduser("/abs"))
    # The two answers are PRINTED and compared by this process rather than
    # compared by the program. `rp == ap` is a real bug on this path, and not
    # one this test should be asserting around: the `==` of two values whose
    # kinds are both unclassified is an ADDRESS comparison, so two identical
    # strings compare unequal (bugs/FORMAL_string_equality_of_two_unclassified_words.md).
    # Comparing the printed strings here is also the stronger assertion — it
    # pins the fallback's actual value rather than a boolean derived from it.
    printf("realpath-missing=[%s]@@", realpath(join(root, "no-such")))
    printf("abspath-missing=[%s]@@", abspath(join(root, "no-such")))
    return 0


def write_file(p):
    h = open(p, "w")
    h.write("0123456789")
    h.close()
    return 0
"""


def build_env_program():
    """`getenv`/`putenv`/`unsetenv`, including the three cases that are easy to
    get wrong: a variable that is set to the empty string (which is not the
    same as unset), a variable that is not set at all (which takes the
    default), and a name that does not look like a name."""
    return """\
from os import getenv, getenv_or, putenv, unsetenv

def main(n):
    printf("unset-default=[%s]@@", getenv("FORMAL_OS_DEFINITELY_UNSET"))
    printf("unset-explicit=[%s]@@", getenv_or("FORMAL_OS_DEFINITELY_UNSET", "d"))
    printf("put=%d@@", putenv("FORMAL_OS_PROBE", "hello"))
    printf("get=[%s]@@", getenv("FORMAL_OS_PROBE"))
    printf("put-empty=%d@@", putenv("FORMAL_OS_PROBE", ""))
    printf("get-empty=[%s]@@", getenv("FORMAL_OS_PROBE"))
    printf("get-empty-default=[%s]@@", getenv_or("FORMAL_OS_PROBE", "d"))
    printf("overwrite=%d@@", putenv("FORMAL_OS_PROBE", "second"))
    printf("get2=[%s]@@", getenv("FORMAL_OS_PROBE"))
    printf("unset=%d@@", unsetenv("FORMAL_OS_PROBE"))
    printf("get3=[%s]@@", getenv("FORMAL_OS_PROBE"))
    printf("get3-default=[%s]@@", getenv_or("FORMAL_OS_PROBE", "gone"))
    printf("unset-again=%d@@", unsetenv("FORMAL_OS_PROBE"))
    return 0
"""


def build(src, out, cwd=None, backend=None):
    """Build `src` for the host's architecture, or for `backend` when given.

    The parameter exists for the REFUSAL rows, which are asserted on both
    architectures: a refusal raised by a shared build pass is one message for
    both, and the group that asserts it should be saying so rather than letting
    a one-sided check stand in for it. Answered rows still build for the host
    alone, because running a second image per row is not what this file is for.
    """
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out,
           src]
    if backend:
        cmd.append(f"--backend={backend}")
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=cwd or HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(out, cwd=None):
    p = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def parse(text):
    """`{key: value}` from the program's `label|index|part|value` records.

    Split on the record terminator rather than on lines, for the reason `REC`
    gives: the records are separated by a token rather than by a decoded byte,
    so reading them does not ask whether the image decoded a literal.
    """
    out = {}
    for chunk in text.split(REC):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        m = re.match(r"^([a-z_-]+)\|(\d+)\|(\d+)\|(.*)$", chunk)
        if m:
            out[(m.group(1), int(m.group(2)), int(m.group(3)))] = m.group(4)
        else:
            out[("?", 0, 0)] = chunk
    return out


def group_strings(tmpdir, verbose):
    src = os.path.join(tmpdir, "os_strings.mojo")
    program, expected = render_strings_program()
    with open(src, "w") as f:
        f.write(program)
    out = os.path.join(tmpdir, "os_strings")
    rc, text = build(src, out)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    got = parse(stdout)
    want = {}
    for line in expected:
        label, ai, part, value = line.split("|", 3)
        want[(label, int(ai), int(part))] = value
    bad = []
    for key in sorted(want, key=lambda k: (k[0], k[1], k[2])):
        if key not in got:
            bad.append(f"{key}: CPython says {want[key]!r}, the module printed "
                       f"NOTHING")
        elif got[key] != want[key]:
            bad.append(f"{key}: CPython says {want[key]!r}, the module says "
                       f"{got[key]!r}")
    if bad:
        return False, ("%d of %d answers differ from CPython's:\n      %s"
                       % (len(bad), len(want), "\n      ".join(bad[:20])))
    if verbose:
        print(f"      {len(want)} answers identical to CPython")
    return True, ""


def render_strings_program():
    return build_strings_program()


def group_posixpath(tmpdir, verbose):
    """`posixpath` — the SAME corpus, the SAME oracle, the other SPELLING.

    `formal/hostmods/posixpath.mojo` re-exports `os/path/__init__.mojo` under
    CPython's own name for it, so what this group asserts is that the
    RE-EXPORT is honest: every name it publishes reaches the same code, over the
    whole corpus and against the same CPython answers. A re-export is the one
    kind of module where "it built" says almost nothing — a name bound to the
    wrong function, or to nothing at all, still builds — so the differential is
    the whole of the test and there is deliberately no second corpus to keep in
    step: a divergence here is a wiring defect, and the corpus is already the one
    `os.path` is measured with.
    """
    src = os.path.join(tmpdir, "posixpath_strings.mojo")
    program, expected = build_strings_program("posixpath")
    with open(src, "w") as f:
        f.write(program)
    out = os.path.join(tmpdir, "posixpath_strings")
    rc, text = build(src, out)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    got = parse(stdout)
    want = {}
    for line in expected:
        label, ai, part, value = line.split("|", 3)
        want[(label, int(ai), int(part))] = value
    bad = []
    for key in sorted(want, key=lambda k: (k[0], k[1], k[2])):
        if key not in got:
            bad.append(f"{key}: CPython says {want[key]!r}, `posixpath` printed "
                       f"NOTHING")
        elif got[key] != want[key]:
            bad.append(f"{key}: CPython says {want[key]!r}, `posixpath` says "
                       f"{got[key]!r}")
    if bad:
        return False, ("%d of %d answers differ from CPython's:\n      %s"
                       % (len(bad), len(want), "\n      ".join(bad[:20])))
    if verbose:
        print(f"      {len(want)} answers identical to CPython, through the "
              f"`posixpath` spelling")
    return True, ""


def make_fixture(tmpdir):
    """The tree the `fs` group operates on, created by THIS process so that
    `os.stat` afterwards has something real to check.

    `realpath` because `/var/folders/…` and `/tmp` are symbolic links on
    macOS: the program prints absolute paths, and comparing those against
    CPython's un-resolved spelling would be a difference in the ORACLE rather
    than in the module.
    """
    root = os.path.realpath(os.path.join(tmpdir, "fx"))
    os.makedirs(os.path.join(root, "d"))
    with open(os.path.join(root, "f.txt"), "w") as f:
        f.write("0123456789")
    with open(os.path.join(root, "perm"), "w") as f:
        f.write("x")
    return root


def group_fs(tmpdir, verbose):
    root = make_fixture(tmpdir)

    def p(*parts):
        return os.path.join(root, *parts)

    # What the filesystem says BEFORE the program runs. Half the assertions
    # have to be taken here rather than after: the program deletes `f.txt` and
    # renames the rest, so asking `os.path.exists` afterwards would be asking
    # about the state the program left rather than the state it was given.
    def facts(tag, path):
        return {f"{tag}-exists": str(int(os.path.exists(path))),
                f"{tag}-isfile": str(int(os.path.isfile(path))),
                f"{tag}-isdir": str(int(os.path.isdir(path)))}

    want = {}
    want.update(facts("file", p("f.txt")))
    want.update(facts("dir", p("d")))
    want.update(facts("missing", p("nope")))
    want.update(facts("under-missing", p("nope", "deeper")))
    want["size"] = str(os.path.getsize(p("f.txt")))
    want["size-missing"] = "-1"
    src = os.path.join(tmpdir, "os_fs.mojo")
    with open(src, "w") as f:
        f.write(FS_PROGRAM.format(root=mojo_string(root)))
    out = os.path.join(tmpdir, "os_fs")
    rc, text = build(src, out)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    got = parse_kv(stdout)

    # …and what it says AFTER, for everything the program itself produced.
    want.update({
        "mkdir": "0",                 # it made this one
        "mkdir-again": "-1",          # EEXIST
        "makedirs": "0",
        "makedirs-again": "0",        # exist_ok: already there is not an error
        "makedirs-deep": "0",
        "rmdir": "0",
        "rmdir-missing": "-1",
        "remove": "0",
        "remove-again": "-1",
        "touch2": "0",
        "touch3": "0",
        "rename": "0",
        "replace": "0",
        "unlink": "0",
        "makedirs-kept": "0",
        "chmod": "0",
        "chmod-missing": "-1",
        "cwd-rel": f"[{posixpath.relpath(p('a'), os.getcwd())}]",
        "chdir": "0",
        "cwd-in": p("a"),
        "chdir-back": "0",
        "chdir-missing": "-1",
        "abspath": posixpath.normpath("/x/./y/../z"),
        "realpath": posixpath.realpath("/"),
        "realpath-missing": f"[{posixpath.abspath(p('no-such'))}]",
        "abspath-missing": f"[{posixpath.abspath(p('no-such'))}]",
        "unlinked-size": "-1",
        "expanduser-tilde": f"[{os.environ['HOME']}]",
        "expanduser-slash": f"[{os.path.join(os.environ['HOME'], 'sub')}]",
        # A `~name` for another user is returned unchanged: reading the
        # password database is not reachable on this target, and CPython also
        # returns the path unchanged when it cannot resolve the name.
        "expanduser-other": "[~someone/sub]",
        "expanduser-abs": "[/abs]",
    })
    for tag, path in (("made", p("a", "b", "c")),
                      ("made-deep", p("p", "q", "r")),
                      ("removed", p("a", "b", "c", "d", "e")),
                      ("removed-file", p("f.txt")),
                      ("gone", p("x1")), ("renamed", p("z2")),
                      ("gone2", p("z1")),
                      ("replaced", p("y2")), ("replaced-away", p("y1")),
                      ("unlinked", p("x2"))):
        want.update(facts(tag, path))
    bad = []
    for k in sorted(want):
        if k not in got:
            bad.append(f"{k}: the module printed nothing for it")
        elif got[k] != want[k]:
            bad.append(f"{k}: module says {got[k]!r}, the filesystem says "
                       f"{want[k]!r}")
    # The mode is checked from OUTSIDE, after the program ran: 384 is 0600.
    try:
        mode = stat.S_IMODE(os.stat(p("perm")).st_mode)
    except OSError as e:
        bad.append(f"chmod produced no file to stat: {e}")
    else:
        if mode != 0o600:
            bad.append(f"chmod(…, 384) left mode {mode:o}, expected 600")
    if bad:
        return False, ("%d disagreements with the filesystem:\n      %s"
                       % (len(bad), "\n      ".join(bad[:20])))
    if verbose:
        print(f"      {len(want)} operations agree with the real filesystem")
    return True, ""


def group_env(tmpdir, verbose):
    src = os.path.join(tmpdir, "os_env.mojo")
    with open(src, "w") as f:
        f.write(build_env_program())
    out = os.path.join(tmpdir, "os_env")
    rc, text = build(src, out)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    env = dict(os.environ)
    env.pop("FORMAL_OS_PROBE", None)
    p = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=tmpdir, env=env)
    if p.returncode != 0:
        return False, f"exit {p.returncode}, stderr {p.stderr.strip()[:200]!r}"
    got = parse_kv(p.stdout)
    # CPython's own answers, in the same order, on the same starting state.
    name = "FORMAL_OS_PROBE"
    os.environ.pop(name, None)
    # Bracketed because the program prints `[%s]`, and an empty value has to
    # be visible as `[]` rather than as nothing at all.
    ref = {
        "unset-default": f"[{os.environ.get(name, '')}]",
        "unset-explicit": f"[{os.environ.get(name, 'd')}]",
        "put": "0",
        "get": "[hello]",
        "put-empty": "0",
        "get-empty": "[]",
        "get-empty-default": "[]",
        "overwrite": "0",
        "get2": "[second]",
        "unset": "0",
        "get3": "[]",
        "get3-default": "[gone]",
        # `unsetenv` on a variable that is not set is 0 on this target, and 0
        # is what the C library returns. CPython has no `unsetenv` at all —
        # `del os.environ[k]` raises `KeyError` — so there is no CPython answer
        # to compare against and the module's own answer is pinned here.
        "unset-again": "0",
    }
    bad = [f"{k}: module says {got.get(k)!r}, CPython says {v!r}"
           for k, v in ref.items() if got.get(k) != v]
    if bad:
        return False, ("%d disagreements with os.environ:\n      %s"
                       % (len(bad), "\n      ".join(bad)))
    if verbose:
        print(f"      {len(ref)} environment answers identical to CPython")
    return True, ""


def group_dirs(tmpdir, verbose):
    """`os.sep()` and the rest of the constants, which are FUNCTIONS here.

    A separate group because these are the ones whose SPELLING had to change:
    a module-level name is not exported as a word across a dylib boundary, so
    CPython's `os.sep` is `sep()` here. The test is that each one returns what
    the constant is, and the group exists so the deviation is pinned rather
    than merely documented.
    """
    src = os.path.join(tmpdir, "os_dirs.mojo")
    with open(src, "w") as f:
        f.write("""\
from os import sep, curdir, pardir, extsep, pathsep, linesep, devnull
from os.path import join, isabs, normpath, join_all, commonprefix
# `os` re-exports the four predicates CPython's `genericpath` defines, so
# BOTH `os.exists` and `os.path.exists` reach ONE definition. Checked in this
# group because its program imports none of those four names from `os.path`,
# and `from os.path import exists as e` would NOT do: an alias in a from-import
# is not honoured for a call into another image
# (bugs/FORMAL_from_import_alias_dangles_the_call.md).
from os import exists, isdir, isfile, getsize

def main(n):
    printf("sep=[%s]@@", sep())
    printf("curdir=[%s]@@", curdir())
    printf("pardir=[%s]@@", pardir())
    printf("extsep=[%s]@@", extsep())
    printf("pathsep=[%s]@@", pathsep())
    printf("linesep=[%s]@@", linesep())
    printf("devnull=[%s]@@", devnull())
    printf("join-sep=[%s]@@", join("a", "b"))
    printf("isabs-root=%d@@", isabs(sep()))
    printf("isabs-rel=%d@@", isabs(curdir()))
    printf("isabs-pardir=%d@@", isabs(pardir()))
    printf("normpath-dot=[%s]@@", normpath(join(curdir(), pardir())))
    xs = ["a", "b", "c"]
    printf("join_all=[%s]@@", join_all(xs))
    ys = ["only"]
    printf("join_all-one=[%s]@@", join_all(ys))
    printf("cp=[%s]@@", commonprefix("abcd", "abxx"))
    printf("reexists-tmp=%d@@", exists("/tmp"))
    printf("reisdir-tmp=%d@@", isdir("/tmp"))
    printf("reisdir-root=%d@@", isdir("/"))
    printf("reisfile-tmp=%d@@", isfile("/tmp"))
    printf("reisfile-devnull=%d@@", isfile(devnull()))
    printf("resize-devnull-ok=%d@@", 1 if getsize(devnull()) >= 0 else 0)
    printf("resize-missing=%d@@", getsize(join(sep(), "no-such-xyz")))
    return 0
""")
    out = os.path.join(tmpdir, "os_dirs")
    rc, text = build(src, out)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    ref = {
        "sep": f"[{os.sep}]",
        "curdir": f"[{os.curdir}]",
        "pardir": f"[{os.pardir}]",
        "extsep": f"[{os.extsep}]",
        "pathsep": f"[{os.pathsep}]",
        "linesep": f"[{os.linesep}]",
        "devnull": f"[{os.devnull}]",
        "join-sep": f"[{os.path.join('a', 'b')}]",
        "isabs-root": "1",
        "isabs-rel": "0",
        "isabs-pardir": "0",
        "normpath-dot": f"[{posixpath.normpath(posixpath.join(os.curdir, os.pardir))}]",
        "join_all": "[a/b/c]",
        "join_all-one": "[only]",
        "cp": f"[{posixpath.commonprefix(['abcd', 'abxx'])}]",
        "reexists-tmp": str(int(os.path.exists("/tmp"))),
        "reisdir-tmp": str(int(os.path.isdir("/tmp"))),
        "reisdir-root": str(int(os.path.isdir("/"))),
        "reisfile-tmp": str(int(os.path.isfile("/tmp"))),
        # `/dev/null` was where the `isfile` DEVIATION used to be pinned: this
        # module's `isfile` was `exists(p) and not isdir(p)`, which is
        # CPython's answer for a regular file, a directory, a link to either
        # and a path that is not there, and 1 where CPython says 0 for a
        # device node, a FIFO or a socket. It is `S_ISREG(st_mode)` read out of
        # the buffer `stat` fills now
        # (bugs/FORMAL_stat_out_parameter_is_unreadable.md), so this line is
        # CPython's own answer and a disagreement is a failure rather than a
        # documented exception. The `stat` group below is where the other two
        # of those three shapes are checked.
        "reisfile-devnull": str(int(os.path.isfile(os.devnull))),
        "resize-devnull-ok": "1",
        "resize-missing": "-1",
    }
    got = parse_kv(stdout)
    bad = [f"{k}: module says {got.get(k)!r}, CPython says {v!r}"
           for k, v in ref.items() if got.get(k) != v]
    if bad:
        return False, ("%d disagreements with the constants:\n      %s"
                       % (len(bad), "\n      ".join(bad)))
    if verbose:
        print(f"      {len(ref)} constants match CPython's values")
    return True, ""


def parse_kv(text):
    """`{key: value}` from `key=value@@` records.

    A key may contain one space (`makedirs-deep`, `isabs-root`), so the split
    is on the FIRST space, not the last — and a key never contains `=`, which
    is what makes one rule enough for both groups.
    """
    got = {}
    for chunk in text.split(REC):
        chunk = chunk.strip("\n").strip()
        if not chunk:
            continue
        k, sep, v = chunk.partition("=")
        if not sep:
            k, _, v = chunk.partition(" ")
        got[k] = v
    return got


BLOB_PROGRAM = """\
from os._syscalls import str_alloc, str_put
from re import escape
from os import listdir, listdir_len, listdir_get, listdir_free

# A CALLER-SUBSCRIPTABLE BLOB, and the two conventions a "blob" actually is.
#
# This is the capability a `collections.Counter` would be built on: `str_alloc`
# mallocs inside the dylib and hands back a POINTER, and this file writes
# through it with `p[i] = ...` and reads it back with `p[i]`.  Neither is a call
# into the module and neither is refused.
#
# Three things this group pins, each of which was measured and each of which is
# a place a reader gets it wrong:
#
#   1. THE LOCAL MUST BE ANNOTATED, and an unannotated one is now REFUSED
#      rather than quietly wrong.  `os._syscalls.str_alloc` is declared
#      `-> str`, so `var p = str_alloc(8)` is a string and its subscript
#      indexes the buffer with no annotation at all.  `re.escape` is declared
#      `-> Pointer[UInt8]`, whose manifest signature is `uint8_t *` — not a
#      kind this path carries into an unannotated local — so `r[0]` used to
#      address the LOCAL's own storage: measured 0/0 where the buffer holds
#      65/66, while `printf("%s", r)` in the same program printed `AB`
#      correctly, and `r[0] = 90` built, ran and exited 0 writing to a slot
#      nothing reads.  A subscript through such a name is refused by name now
#      (BLOB_UNTYPED_PROGRAM below); the annotated spelling is the answer and is
#      still here, answering 65/66.
#   2. THERE ARE TWO CONVENTIONS, not one.  `str_alloc` is RAW: byte 0 is byte
#      0.  `listdir` is HEADERED: byte 0 is the entry COUNT and byte `1 + i` is
#      entry `i`'s `malloc`'d pointer.  A container keyed on 0 collides with the
#      header, and the collision is silent.
#   3. THE HEADERED ONE IS NOT STORE-SAFE, and that is now REFUSED rather than
#      discovered at run time.  `listdir_free` frees `names[1 + i]` as a
#      pointer, so writing an integer into an entry word left the module freeing
#      a small integer: the build was silent and the program died in `free` with
#      SIGABRT, exit 134, on both architectures.  The `os` module now PUBLISHES
#      the convention (the `owned_blob` contract in its dylib manifest, declared
#      once in `formal/imports.py`'s `HOST_OWNED_BLOBS`) and an importer that
#      stores into such a blob is refused BY NAME, at the store, naming which
#      word is the count and which are the pointers.  BLOB_STORE_PROGRAM below is
#      that program, and this group asserts the refusal on both architectures as
#      well as the answers above.
def main(n):
    # -- the raw convention ------------------------------------------------
    var p = str_alloc(64)
    p[0] = 65
    p[1] = 66
    p[2] = 0
    printf("b0=%d@@", p[0])
    printf("b1=%d@@", p[1])
    printf("reread=%d@@", p[1])
    printf("untouched=%d@@", p[40])
    # The module's own writer agrees with what the caller wrote by subscript,
    # which is what makes this one buffer and not two private ones.
    printf("put=%d@@", str_put(p, 0, "ZZ", 2))

    # -- the annotation the pointer convention needs -----------------------
    # `escape` is declared `-> Pointer[UInt8]`, so the local must say so, and the
    # unannotated spelling is a REFUSAL now rather than a silent 0/0 (see
    # BLOB_UNTYPED_PROGRAM, which is that program).
    var annotated: Pointer[UInt8] = escape("AB")
    printf("annotated=%d,%d@@", annotated[0], annotated[1])

    # -- the headered convention, read the way it is safe to read ----------
    var names = listdir({dirpath})
    var n_entries = listdir_len(names)
    printf("entries=%d@@", n_entries)
    printf("entry0=%s@@", listdir_get(names, 0))
    printf("entry1=%s@@", listdir_get(names, 1))
    # Out of range in both directions, because `listdir_get` defines both and a
    # blob has no bounds of its own for a caller to trip over.
    printf("oob=%s@@", listdir_get(names, n_entries))
    printf("neg=%s@@", listdir_get(names, -1))
    listdir_free(names)
    return 0
"""


BLOB_STORE_PROGRAM = """\
from os import listdir, listdir_len, listdir_free

# The defect `d9874a93` fixed: the build was silent on both architectures and the
# program died in the module's own `free` with SIGABRT, because word 1 of a
# `listdir` blob is entry 0's POINTER and `listdir_free` calls `free` on whatever
# word it finds there.
def main() -> Int:
    var names = listdir("{dirpath}")
    printf("before=%d", listdir_len(names))
    names[1] = 5
    printf("after=%d", listdir_len(names))
    listdir_free(names)
    printf("freed")
    return 0
"""


# The store inside a HELPER, which is the shape a `Counter`-shaped consumer is
# written as and the one that says the refusal is not a statement about the
# variable it names: `poke` never mentions `os`, and the evidence that its
# parameter is a module-owned blob is the CALL SITE in `main`.  Also the
# pass-through, for the same reason one hop further out: `grab` returns the blob
# and binds nothing else.
BLOB_STORE_HELPER_PROGRAM = """\
from os import listdir, listdir_free

def grab(path) -> Int:
    var names = listdir(path)
    return names

def poke(names) -> Int:
    names[0] = 1
    return 0

def main() -> Int:
    var names = grab("{dirpath}")
    poke(names)
    listdir_free(names)
    return 0
"""


# An UNTYPED binding of a cross-image POINTER, which used to be a silent wrong
# answer and is a refusal by name now.  Both halves of the pair, because they
# were different failures: the READ gave 0 where the buffer holds 65 while
# `printf("%s", r)` in the same program printed `AB`, and the STORE built, ran and
# exited 0 writing to a slot nothing reads.
BLOB_UNTYPED_PROGRAM = """\
from re import escape

def main() -> Int:
    var r = escape("AB")
    printf("%s", r)
    printf("%d,%d", r[0], r[1])
    r[1] = 90
    return 0
"""

# …and the same trap through `os`, whose `listdir` used to be declared `-> int`
# — a declaration that was false about a value that is an address, and the reason
# an unannotated `names[0]` answered 704698368 (a heap address) where
# `listdir_len` says 2.  The declaration is `Pointer[Int64]` now, so the manifest
# says `int64_t *` and this is refused for the same reason and with the same
# repair.
BLOB_UNTYPED_LISTDIR_PROGRAM = """\
from os import listdir, listdir_free

def main() -> Int:
    var names = listdir("{dirpath}")
    printf("%d", names[0])
    listdir_free(names)
    return 0
"""

# What each refusal has to NAME, and the facts a reader cannot get from the type:
# the subscript as the source spells it, and the module whose declaration says the
# value is a pointer.
BLOB_STORE_REFUSAL = "`names[1]` writes into a blob os OWNS"
BLOB_UNTYPED_REFUSAL = ("subscripts `r`, whose value came from `escape` in re "
                        "— and that export's own declaration is a POINTER")
BLOB_UNTYPED_LISTDIR_REFUSAL = (
    "subscripts `names`, whose value came from `listdir` in os")


def build_blob_program(tmpdir):
    """`BLOB_PROGRAM` with a fixture directory holding exactly two files.

    `listdir`'s answer is the real filesystem's, so the group asks the same
    question this file has asked everywhere else: build and RUN, and compare
    with what CPython says about the same directory.  A module that returned a
    plausible count rather than doing the listing could not pass.  Compared as
    a SET, because `listdir`'s own docstring says the order is the C library's
    and CPython's is not.
    """
    d = blob_fixture_dir(tmpdir)
    return BLOB_PROGRAM.replace("{dirpath}", mojo_string(d)), sorted(
        os.listdir(d))


def blob_fixture_dir(tmpdir):
    """The two-entry directory every blob program is pointed at.

    Split out of `build_blob_program` because the store programs are pointed at
    the same directory and must see the same two entries — `listdir_len`'s
    answer is the fixture's, and a store case that ran against a different
    directory would be measuring something else.
    """
    d = os.path.join(tmpdir, "blobdir")
    os.makedirs(d, exist_ok=True)
    for name in ("a.txt", "b.txt"):
        with open(os.path.join(d, name), "w") as f:
            f.write("x")
    return d


def group_blob(tmpdir, verbose):
    src = os.path.join(tmpdir, "os_blob.mojo")
    program, entries = build_blob_program(tmpdir)
    d = blob_fixture_dir(tmpdir)
    with open(src, "w") as f:
        f.write(program)
    out = os.path.join(tmpdir, "os_blob")
    rc, text = build(src, out)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    got = parse_kv(stdout)
    bad = []
    for k, v in {"b0": "65", "b1": "66", "reread": "66", "untouched": "0",
                 "put": "2", "entries": str(len(entries)),
                 "oob": "", "neg": "",
                 # `re.escape("AB")` is `AB`, so 65/66 -- through the
                 # ANNOTATED local, which is the spelling that works.
                 "annotated": "65,66"}.items():
        if got.get(k) != v:
            bad.append(f"{k}: module says {got.get(k)!r}, the case says {v!r}")
    for k, i in (("entry0", 0), ("entry1", 1)):
        if got.get(k) not in entries:
            bad.append(f"{k}: module says {got.get(k)!r}, which is not one of "
                       f"the directory's entries {entries}")
    if bad:
        return False, ("%d disagreements:\n      %s"
                       % (len(bad), "\n      ".join(bad)))
    # The store, which must be REFUSED rather than run: a build that accepts it
    # produces an image that aborts inside the module's own `free`, and the
    # assertion is the refusal's WORDS as well as its existence, because a
    # refusal that named the variable but not the owner would leave the reader
    # with `names` to stare at rather than with the convention.
    for label, program, needle in (
            ("os_blob_store", BLOB_STORE_PROGRAM, BLOB_STORE_REFUSAL),
            ("os_blob_store_helper", BLOB_STORE_HELPER_PROGRAM,
             "`names[0]` writes into a blob os OWNS"),
            ("os_blob_untyped", BLOB_UNTYPED_PROGRAM, BLOB_UNTYPED_REFUSAL),
            ("os_blob_untyped_listdir", BLOB_UNTYPED_LISTDIR_PROGRAM,
             BLOB_UNTYPED_LISTDIR_REFUSAL),
    ):
        store_src = os.path.join(tmpdir, label + ".mojo")
        with open(store_src, "w") as f:
            f.write(program.replace("{dirpath}", mojo_string(d)))
        for backend in ("arm64", "x86_64"):
            rc, text = build(store_src, os.path.join(tmpdir, label), None,
                             backend)
            if rc == 0:
                return False, (f"{label} [{backend}]: built a store into a blob "
                               f"`os` owns; the image aborts in listdir_free "
                               f"with SIGABRT, so a build here is the wrong "
                               f"answer, not a passing one")
            if needle not in text:
                return False, (f"{label} [{backend}]: refused, but not naming "
                               f"the store and its owner ({needle!r}): "
                               f"{text.strip()[-300:]}")
    if verbose:
        print(f"      9 blob facts; {len(entries)} directory entries, compared "
              f"as a set because listdir's order is the C library's; 2 stores "
              f"and 2 untyped subscripts refused by name on both architectures")
    return True, ""


GROUPS = {
    "strings": group_strings,
    "posixpath": group_posixpath,
    "fs": group_fs,
    "env": group_env,
    "dirs": group_dirs,
    "blob": group_blob,
}


def main():
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
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:  # report, do not mask
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
