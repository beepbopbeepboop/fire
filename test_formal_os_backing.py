#!/usr/bin/env python3
r"""The constructs that back `os`: a byte read, a pointer subscript, a C
out-parameter, and a directory name. Built, EXECUTED, and compared with CPython.

    python3 test_formal_os_backing.py [-v] [case ...]

Why these four and not the rest of the `os` surface. `formal/hostmods/os`
could not answer three questions its callers ask on every path operation, and
each of them was a SILENT WRONG ANSWER rather than a refusal:

  * `s[i]` on a `String`-annotated PARAMETER read the first eight CHARACTERS of
    the string as a list blob's element count and then loaded at
    `base + 8 + 8*count` — a text-section address. `f("AB")[0]` returned
    -8070450326089498624 where 65 is the answer
    (bugs/CODEGEN_string_parameter_subscript_reads_count_field.md).
  * `p[i]` on a `Pointer[UInt8]` was the same question `p.value()` already
    answered, asked in a spelling only one of the two was routed: -1879048144
    for the first four characters of a string read as a little-endian word, and
    a bare `exit 1` with no message for a `malloc`'d buffer whose count is 0
    (bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md).
  * `stat(2)`'s out-parameter could not be read at all, so `isfile` was
    `exists and not isdir` — 1 for `/dev/null` where CPython says 0 — and
    `islink`, `lexists` and `samefile` did not exist
    (bugs/FORMAL_stat_out_parameter_is_unreadable.md).
  * `readdir(3)`'s `d_name` is a `char[]` inside a struct the source never
    declares, so there was no name to read and therefore no `listdir`
    (bugs/FORMAL_listdir_no_run_time_sequence.md — the name half of it).

Why an ORACLE and not a table. Every case here that has a CPython answer is
checked against CPython running the same computation, and every case that has a
filesystem behind it is checked against `os.stat`/`os.listdir` in THIS process.
A table written here would be a second thing to be wrong; the point of the
suite is that the module and CPython cannot disagree without the suite saying
so.

BOTH ARCHITECTURES. Every case is built for arm64 and for x86-64 and the two
answers must be EQUAL, and where the case has a CPython answer all three must
be. The two backends are separate implementations of the same lowering, so
their agreement is evidence and CPython is the arbiter of whether the agreement
is right. x86-64 runs under Rosetta 2 on Apple Silicon, and is SKIPPED (not
failed) on a host with no x86-64 support at all, with the reason printed.

Every case EXECUTES. A lowering that builds a plausible wrong image is exactly
what this suite exists to catch, and no case here settles for a build.
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

# The record terminator, for the reason `test_formal_os.py` gives: a Mojo string
# literal's `\n` is not unescaped on this path, so a program here emits its
# records back to back and this is what separates them.
REC = "@@"

S_IFMT = 0o170000
S_IFREG = 0o100000
S_IFDIR = 0o040000
S_IFLNK = 0o120000
S_IFIFO = 0o010000
S_IFSOCK = 0o140000
S_IFCHR = 0o020000
S_IFBLK = 0o060000


class Case:
    """One program, and what has to be true of it.

    Exactly one of three modes, and the mode is a constructor argument rather
    than something inferred, so a case cannot accidentally assert nothing:

      * `expect` — a `{key: value}` dict the printed records must equal;
      * `oracle` — a zero-argument callable returning that dict, for the cases
        whose expected values are CPython's to answer (a filesystem fact);
      * `refusal` — a substring the BUILD ERROR must contain, for a construct
        that has to be refused rather than answered.

    Every program below ends its records with `@@` rather than a newline, for
    the reason `test_formal_os.py` gives: a Mojo string literal's `\n` is not
    unescaped on this path, so a formal image prints the two characters backslash and
    `n` and a record-structured program has to choose its own terminator.
    """

    def __init__(self, name, source, expect=None, oracle=None, refusal=None,
                 archs=None):
        self.name = name
        self.source = source
        self.expect = expect
        self.oracle = oracle
        self.refusal = refusal
        # Which architectures this case can run on, or None for all of them.
        # One case needs it: anything that imports `os`/`os.path` builds a
        # module dylib that calls the C library, and such a dylib is arm64-only
        # on this backend — the loader refuses it under x86-64 with
        # `main executable failed strict validation`
        # (bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md, and
        # the note at the top of `formal/hostmods/os/__init__.mojo`). The cases
        # that are pure BACKEND constructs run on both, because that agreement
        # is the evidence they exist for.
        self.archs = archs


# ── 1. `s[i]` on a String-annotated parameter ──────────────────────────────
#
# The parameter is the whole case. A string bound to a LOCAL in the same
# function was already right, and a `String` annotation is the only thing that
# distinguishes this spelling from an unannotated word.
CASES = []

CASES.append(Case(
    "string_param_subscript",
    '''\
def first(s: String):
    return s[0]


def second(s: String, i):
    return s[i]


def main(n):
    printf("a=%d@@", first("AB"))
    printf("b=%d@@", first("/x"))
    printf("c=%d@@", first("~"))
    printf("d=%d@@", second("hello", 4))
    printf("e=%d@@", second("hello", 0))
    return 0
''',
    {"a": "65", "b": "47", "c": "126", "d": "111", "e": "104"},
))

# A ONE-CHARACTER STRING is the case that separates "a byte" from "the count",
# because a blob walk on a one-byte string reads its own NUL and length-1 text
# as the count.
CASES.append(Case(
    "string_param_subscript_one_char",
    '''\
def at(s: String, i):
    return s[i]


def main(n):
    printf("a=%d@@", at("A", 0))
    printf("b=%d@@", at("A", 1))
    printf("c=%d@@", at("", 0))
    return 0
''',
    {"a": "65", "b": "0", "c": "0"},
))

# A `String` parameter that came from another function, so the value is a
# `malloc`'d buffer rather than a literal in `__TEXT`. The two spellings of a
# string subscript have to agree on both.
CASES.append(Case(
    "string_param_subscript_computed",
    '''\
def copy(s: String):
    var d: Pointer[UInt8] = malloc(64)
    memset(d, 0, 64)
    memcpy(d, s, strlen(s))
    return d


def at(s: String, i):
    return s[i]


def main(n):
    c = copy("hello")
    printf("a=%d@@", at(c, 0))
    printf("b=%d@@", at(c, 4))
    printf("c=%d@@", strlen(c))
    return 0
''',
    {"a": "104", "b": "111", "c": "5"},
))

# ── 2. `p[i]` on a declared pointer ───────────────────────────────────────
#
# One case per pointee width, because the width is the whole answer and a
# backend that emitted one instruction for all of them would pass the `UInt8`
# row. `Pointer[Int32]` and `Pointer[Int64]` are the two that were reachable as
# a scale bug: `base + i` is the SECOND element for anything wider than a byte.
CASES.append(Case(
    "pointer_subscript_u8",
    '''\
def at(b: Pointer[UInt8], i):
    return b[i]


def main(n):
    var p: Pointer[UInt8] = malloc(16)
    memcpy(p, "hello", 6)
    printf("a=%d@@", at(p, 0))
    printf("b=%d@@", at(p, 4))
    printf("c=%d@@", p[1])
    printf("d=%d@@", p[5])
    printf("e=%d@@", at(p, 5))
    return 0
''',
    {"a": "104", "b": "111", "c": "101", "d": "0", "e": "0"},
))

CASES.append(Case(
    "pointer_subscript_i32",
    '''\
def main(n):
    var q: Pointer[Int32] = malloc(32)
    q[0] = 1000
    q[1] = 2000
    q[2] = 3000
    printf("a=%d@@", q[0])
    printf("b=%d@@", q[1])
    printf("c=%d@@", q[2])
    printf("d=%d@@", q[3])
    return 0
''',
    {"a": "1000", "b": "2000", "c": "3000", "d": "0"},
))

CASES.append(Case(
    "pointer_subscript_i64",
    '''\
def main(n):
    var q: Pointer[Int64] = malloc(32)
    q[0] = 5
    q[1] = 6
    printf("a=%d@@", q[0])
    printf("b=%d@@", q[1])
    printf("c=%d@@", q[2])
    return 0
''',
    {"a": "5", "b": "6", "c": "0"},
))

# `p[i]` and `p.value()` are the same question, so they must give the same
# answer. Measured before the route existed, they did not: `p[0]` on a
# `Pointer[UInt8]` was -1879048144 and `p.value()` was 97.
CASES.append(Case(
    "pointer_subscript_agrees_with_value",
    '''\
def main(n):
    var p: Pointer[UInt8] = malloc(16)
    memcpy(p, "abc", 4)
    v = p.value()
    i = p[0]
    printf("a=%d@@", v)
    printf("b=%d@@", i)
    printf("c=%d@@", v - i)
    return 0
''',
    {"a": "97", "b": "97", "c": "0"},
))

# A STORE through a pointer, and an AUGMENTED one. The store is the case that
# catches an 8-byte store into a 1-byte element: it overwrites the seven bytes
# after it, which for a `malloc`'d buffer is a silent corruption of whatever
# the caller put there and for a short buffer is a fault in someone else's
# memory.
CASES.append(Case(
    "pointer_subscript_store",
    '''\
def main(n):
    var p: Pointer[UInt8] = malloc(16)
    memcpy(p, "hello", 6)
    p[1] = 65
    p[4] = 90
    printf("a=[%s]@@", p)
    return 0
''',
    # "hello" with [1] = 'A' and [4] = 'Z'. Both stores are ONE byte: an 8-byte
    # store through [1] would have written 'A' and seven zero bytes over "ello"
    # and the string would have ended there.
    {"a": "[hAllZ]"},
))

# x86-64 REFUSES an augmented assignment through a subscript outright
# (`augmented assignment target must be a plain name`), which is an honest
# refusal rather than a wrong answer and is not what this case is about.
CASES.append(Case(
    "pointer_subscript_augmented",
    '''\
def main(n):
    var q: Pointer[Int32] = malloc(16)
    q[0] = 10
    q[0] += 5
    q[1] = 3
    q[1] *= 7
    printf("a=%d@@", q[0])
    printf("b=%d@@", q[1])
    return 0
''',
    {"a": "15", "b": "21"},
    archs=["arm64"],
))

# A NEGATIVE index moves the address backwards, which is C's subscript and is
# what a `->value()` idiom would want. The scale is signed for the same reason.
CASES.append(Case(
    "pointer_subscript_negative_index",
    '''\
def main(n):
    var p: Pointer[UInt8] = malloc(16)
    memcpy(p, "abcd", 5)
    printf("a=%d@@", p[3])
    printf("b=%d@@", p[1 - 1])
    return 0
''',
    {"a": "100", "b": "97"},
))

# ── 3. The refusals ───────────────────────────────────────────────────────
#
# A wrong answer is worse than a diagnostic, so each of these has to be a BUILD
# refusal naming the construct. A program that builds here and returns a number
# is a failure of this suite, not a pass.
#
# `p[0]` where `p` is a POINTER WITH NO POIN-TYPE STATED. Not the blob walk,
# and not a bounds check against whatever word is at offset 0.
CASES.append(Case(
    "refuse_unstated_pointee",
    '''\
def main(n):
    var p: Pointer = malloc(16)
    q = p[0]
    printf("q=%d@@", q)
    return 0
''',
    refusal="p[i]",
))

# A STRUCT pointee has no width and no field list, so `p[i]` would need to know
# the field at offset i*8.
CASES.append(Case(
    "refuse_struct_pointee",
    '''\
struct Box:
    var a: Int64
    var b: Int64


def main(n):
    var p: Pointer[Box] = malloc(32)
    q = p[0]
    printf("q=%d@@", q)
    return 0
''',
    refusal="STRUCT",
))

# ── 4. `==` between two computed strings ───────────────────────────────────
#
# The third construct, and the one whose failure mode is a correct program
# taking the wrong branch rather than a wrong number. Two cases, and they are
# the two halves of the fix:
#
#   * an ANNOTATED callee classifies at the CALL SITE, across a dylib boundary,
#     so `dirname(p) == "a"` is a content compare. Measured FALSE before the
#     annotations, on both backends.
#   * an UNANNOTATED one is REFUSED rather than compared, so a program that
#     means to compare two strings and forgot the annotation gets a diagnostic
#     naming the fix instead of a silent FALSE.
#
# The null test is the third case and it is a DIVERGENCE, pinned here so it
# cannot change unnoticed: `p == 0` on a `char *` is "is it there", which is
# what every function in `os` means by it, and it is a word compare. Python has
# no such spelling — `s == 0` is False for every string there — so this is
# recorded rather than claimed to match anything.
CASES.append(Case(
    "string_equality_annotated_callee",
    '''\
from os.path import join, dirname, basename, normpath

def main(n):
    p = join("a", "b")
    printf("a=%d@@", 1 if dirname(p) == "a" else 0)
    printf("b=%d@@", 1 if dirname(p) == "b" else 0)
    printf("c=%d@@", 1 if basename(p) == "b" else 0)
    printf("d=%d@@", 1 if normpath(p) == "a/b" else 0)
    printf("e=%d@@", 1 if dirname(p) != "b" else 0)
    return 0
''',
    {"a": "1", "b": "0", "c": "1", "d": "1", "e": "1"},
    archs=["arm64"],
))

CASES.append(Case(
    "refuse_unannotated_string_equality",
    '''\
def mk(t):
    var p: Pointer[UInt8] = malloc(64)
    snprintf(p, 64, "%s", t)
    return p


def main(n):
    c = mk("abc")
    d = mk("abc")
    printf("%d@@", 1 if c == d else 0)
    return 0
''',
    refusal="CALLEE",
))

# The call form with no local binding, and the parameter form beside it. The
# first is refused; the second is left alone on purpose, and this is the case
# that says so — see `model.string_compare_word_refusal`'s "two unannotated
# PARAMETERS" bullet for why a diagnostic there would be in front of correct
# code.
CASES.append(Case(
    "refuse_unannotated_string_equality_call_form",
    '''\
def mk(t):
    var p: Pointer[UInt8] = malloc(64)
    snprintf(p, 64, "%s", t)
    return p


def main(n):
    printf("%d@@", 1 if mk("abc") == mk("abc") else 0)
    return 0
''',
    refusal="CALLEE",
))

# ── 5. `stat(2)`'s out-parameter, against the real filesystem ──────────────
#
# Every field this module reads, on every shape a path can have, compared with
# CPython's own `os.stat` in this process. The shapes are the point: a layout
# that is right for a regular file is right for all of them, and a case set
# with only a regular file in it would not know that.
STAT_PROGRAM = '''\
from os.path import isfile, isdir, islink, lexists, exists, getsize
from os.path import stat_mode, stat_size, stat_ino, stat_dev, stat_nlink
from os.path import stat_uid, stat_gid, stat_blocks, stat_blksize

def show(p):
    printf("pred isfile=%d isdir=%d islink=%d lexists=%d exists=%d@@",
           isfile(p), isdir(p), islink(p), lexists(p), exists(p))
    printf("m1 mode=%d nlink=%d uid=%d gid=%d@@",
           stat_mode(p, 1), stat_nlink(p, 1), stat_uid(p, 1), stat_gid(p, 1))
    printf("m2 size=%d ino=%d dev=%d blocks=%d blksize=%d@@",
           stat_size(p, 1), stat_ino(p, 1), stat_dev(p, 1),
           stat_blocks(p, 1), stat_blksize(p, 1))
    printf("l1 lmode=%d lsize=%d lino=%d@@",
           stat_mode(p, 0), stat_size(p, 0), stat_ino(p, 0))
    printf("g1 getsize=%d@@", getsize(p))


def main(n):
    show("@@PATH@@")
    return 0
'''


def _stat_oracle(p):
    """CPython's answers for one path, in the keys `STAT_PROGRAM` prints.

    `os.lstat` for the `l*` keys, because that is what `follow` = 0 asks for,
    and `os.stat` for the rest. A path CPython cannot stat is answered as
    -1/`0` rather than raising, because this path has no exception to raise and
    a case that raised would be testing CPython's error handling rather than the
    module.
    """
    out = {}
    out["pred"] = "isfile=%d isdir=%d islink=%d lexists=%d exists=%d" % (
        int(os.path.isfile(p)), int(os.path.isdir(p)), int(os.path.islink(p)),
        int(os.path.lexists(p)), int(os.path.exists(p)))
    try:
        s = os.stat(p)
    except OSError:
        s = None
    ls = None
    try:
        ls = os.lstat(p)
    except OSError:
        pass

    def field(st, name):
        return -1 if st is None else getattr(st, name)

    out["m1"] = "mode=%d nlink=%d uid=%d gid=%d" % (
        field(s, "st_mode"), field(s, "st_nlink"), field(s, "st_uid"),
        field(s, "st_gid"))
    out["m2"] = "size=%d ino=%d dev=%d blocks=%d blksize=%d" % (
        field(s, "st_size"), field(s, "st_ino"), field(s, "st_dev"),
        field(s, "st_blocks"), field(s, "st_blksize"))
    out["l1"] = "lmode=%d lsize=%d lino=%d" % (
        field(ls, "st_mode"), field(ls, "st_size"), field(ls, "st_ino"))
    try:
        g = os.path.getsize(p)
    except OSError:
        g = -1
    out["g1"] = "getsize=%d" % g
    return out


# The name each shape is created under, and what makes it. `None` for the
# shapes that are already there on every macOS; the rest are created in the
# fixture so the test does not depend on the machine's `/dev`.
#
#   regular  a plain file with known contents
#   dir      a directory
#   fifo     os.mkfifo — the shape `isfile` used to get wrong
#   sock     a bound AF_UNIX socket — the third shape it used to get wrong
#   link     a symbolic link to the regular file
#   dangle   a symbolic link to a path that is not there
#   dl       a symbolic link to the directory
#   hard     a hard link to the regular file
#   chr      a character device, if the machine has one
SHAPES = ["regular", "dir", "fifo", "sock", "link", "dangle", "dl", "hard"]


def make_shapes(root):
    """Build every shape under `root`; return `{shape: absolute path}`.

    `os.mkfifo` and a bound socket are the two shapes that are not a file and
    not a directory, and they are the two `exists and not isdir` cannot tell
    from a regular file. A socket is left bound deliberately: an unlinked
    socket has no name, and `stat` on a name is the question.
    """
    import socket
    paths = {}
    reg = os.path.join(root, "reg")
    with open(reg, "w") as f:
        f.write("0123456789")
    paths["regular"] = reg
    d = os.path.join(root, "dir")
    os.makedirs(os.path.join(d, "inner"))
    paths["dir"] = d
    fifo = os.path.join(root, "fifo")
    try:
        os.mkfifo(fifo)
        paths["fifo"] = fifo
    except (OSError, AttributeError):
        pass
    sock_path = os.path.join(root, "sock")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(sock_path)
        # The socket stays bound for the life of the fixture; `socket` objects
        # close on garbage collection and an unlinked socket has no name, so
        # the module is handed the descriptor list by `SOCK_KEEP`.
        SOCK_KEEP.append(s)
        paths["sock"] = sock_path
    except (OSError, AttributeError):
        pass
    link = os.path.join(root, "link")
    os.symlink(reg, link)
    paths["link"] = link
    paths["dangle"] = os.path.join(root, "dangle")
    os.symlink(os.path.join(root, "no-such-target"), paths["dangle"])
    paths["dl"] = os.path.join(root, "dl")
    os.symlink(d, paths["dl"])
    paths["hard"] = os.path.join(root, "hard")
    os.link(reg, paths["hard"])
    # A character device, if this machine has one under the fixture root's
    # filesystem. `/dev/null` is the one that is on every macOS, and it is the
    # case `test_formal_os.py` pins, so it is used directly rather than
    # created.
    if os.path.exists("/dev/null"):
        paths["chr"] = "/dev/null"
    return paths


SOCK_KEEP = []


# ── 6. `listdir` and `walk`, against the real filesystem ───────────────────
#
# The fourth construct, and the one with the most surface: a run-time-length
# sequence, which is a blob in `malloc`'d memory rather than a frame blob, and
# a `struct dirent` whose name is bytes at a fixed offset.
#
# The program prints the listing of a FIXTURE TREE this process created, and
# the oracle is `os.listdir` in this process. Both sides see the same
# directory, so the entries, their order and their count have to agree — and
# `os.listdir`'s order is the filesystem's, which is the order `readdir` gives
# and therefore the order CPython gives.
LISTDIR_PROGRAM = """\
from os import listdir, listdir_len, listdir_get, listdir_free
from os import walk, walk_free

def show_listing(tag, p):
    names = listdir(p)
    n = listdir_len(names)
    printf("L %s n=%d@@", tag, n)
    i = 0
    while i < n:
        printf("E %s %d [%s]@@", tag, i, listdir_get(names, i))
        i = i + 1
    printf("L %s oob=[%s]@@", tag, listdir_get(names, n))
    printf("L %s neg=[%s]@@", tag, listdir_get(names, 0 - 1))
    listdir_free(names)
    return 0


def show_walk(d, p):
    paths = walk(p, d)
    n = listdir_len(paths)
    printf("W %d n=%d@@", d, n)
    i = 0
    while i < n:
        q = listdir_get(paths, i)
        printf("P %d %d [%s]@@", d, i, q)
        printf("C %d %d %d@@", d, i, listdir_len(listdir(q)))
        i = i + 1
    walk_free(paths)
    return 0


def main(n):
    show_listing("root", "@@ROOT@@")
    show_listing("dir", "@@ROOT@@/dir")
    show_listing("inner", "@@ROOT@@/dir/inner")
    show_listing("link", "@@ROOT@@/link")
    show_listing("dangle", "@@ROOT@@/dangle")
    show_listing("missing", "@@ROOT@@/no-such-dir")
    show_listing("file", "@@ROOT@@/reg")
    show_walk(9, "@@ROOT@@")
    show_walk(1, "@@ROOT@@")
    show_walk(0, "@@ROOT@@")
    return 0
"""


def _listdir_oracle(root):
    """CPython's answers for `LISTDIR_PROGRAM` over the fixture tree.

    The listing, in `os.listdir` order — which is `readdir` order, the order
    this program's `readdir` walk also produces.

    The walk is `os.walk(root, followlinks=True)` filtered by depth, and BOTH
    of those are deliberate. `followlinks=True` because `os.walk` does NOT
    follow a directory symlink by default and this module's `walk` DOES — it
    asks `isdir`, which follows, and `formal/hostmods/os/__init__.mojo`'s
    `walk` says so. The fixture has a `dl` that is exactly that case, so the
    question is asked rather than assumed, and the count at depth 1 is the
    thing that would move if the two disagreed. The depth FILTER is because
    `os.walk` has no depth argument, and a hand-rolled walk here would be the
    program under test checked against itself.
    """
    out = {}
    for tag, path in (("root", root),
                      ("dir", os.path.join(root, "dir")),
                      ("inner", os.path.join(root, "dir", "inner")),
                      ("link", os.path.join(root, "link")),
                      ("dangle", os.path.join(root, "dangle")),
                      ("missing", os.path.join(root, "no-such-dir")),
                      ("file", os.path.join(root, "reg"))):
        try:
            names = os.listdir(path)
        except OSError:
            out[f"L {tag} n"] = "-1"
            out[f"L {tag} oob"] = ""
            out[f"L {tag} neg"] = ""
            continue
        out[f"L {tag} n"] = str(len(names))
        for i, nm in enumerate(names):
            out[f"E {tag} {i}"] = nm
        out[f"L {tag} oob"] = ""
        out[f"L {tag} neg"] = ""
    for d in (9, 1, 0):
        rows = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > d:
                continue
            rows.append((dirpath, len(dirnames) + len(filenames)))
        out[f"W {d} n"] = str(len(rows))
        for i, (dirpath, count) in enumerate(rows):
            out[f"P {d} {i}"] = dirpath
            out[f"C {d} {i}"] = str(count)
    return out


def build(src, out, arch):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "--backend=" + arch, "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(out, arch):
    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", out]        # Rosetta 2
    p = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout, p.stderr


def parse_listdir(text):
    """The `listdir`/`walk` program's records, keyed the way the oracle is.

    Two record shapes and one key: `L root n=8` and `E root 0 [reg]` both
    become `("<what>", "<a>", "<b>")` with a value, so a directory listing is
    compared ENTRY BY ENTRY AND IN ORDER rather than as a set of names — a
    listing is exactly where two entries can share a name, and a comparison
    keyed on the name alone would not see the difference.

    Written as a split rather than one regex because the two shapes differ in
    where the value sits, and a single pattern for that is a pattern with an
    optional group in the middle of it and no way to tell which branch matched.
    """
    got = {}
    for chunk in text.split(REC):
        chunk = chunk.strip("\n").strip()
        if not chunk:
            continue
        parts = chunk.split(" ", 3)
        what = parts[0]
        a = parts[1] if len(parts) > 1 else ""
        b = parts[2] if len(parts) > 2 else ""
        rest = parts[3] if len(parts) > 3 else ""
        if "=" in b and not rest:
            b, _, rest = b.partition("=")
        if rest.startswith("[") and rest.endswith("]"):
            rest = rest[1:-1]
        got[(what, a, b)] = rest
    return got


def parse(text):
    """`{key: value}` from the image's records.

    Two record shapes, because the two halves of this suite ask different
    questions of a program: a scalar case prints `key=value` and a
    filesystem case prints `key value` with a `key=value` answer inside it
    (several facts at once, in one order, with the whole line compared). Both
    are split on the FIRST separator, and a key never contains one.
    """
    got = {}
    for chunk in text.split(REC):
        chunk = chunk.strip("\n").strip()
        if not chunk:
            continue
        k, sep, v = chunk.partition(" ")
        if not sep:
            k, sep, v = chunk.partition("=")
        if sep:
            got[k] = v
    return got


def rosetta():
    """Whether this host can run an x86-64 image, or None when it cannot tell."""
    if platform.machine() not in ("arm64", "aarch64"):
        return False
    if platform.system() != "Darwin":
        return None
    return True


# ── the runner ────────────────────────────────────────────────────────────

def run_listdir_case(arch, tmpdir, fixture, verbose):
    """(ok, detail) for the `listdir`/`walk` program on one architecture."""
    src = os.path.join(tmpdir, "os_listdir.mojo")
    with open(src, "w") as f:
        f.write(LISTDIR_PROGRAM.replace("@@ROOT@@", fixture))
    out = os.path.join(tmpdir, "os_listdir." + arch)
    rc, text = build(src, out, arch)
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out, arch)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    want = {(k.split()[0], k.split()[1] if len(k.split()) > 1 else "",
            k.split()[2] if len(k.split()) > 2 else ""): v
            for k, v in _listdir_oracle(fixture).items()}
    got = parse_listdir(stdout)
    bad = [f"{k}: the image says {got.get(k)!r}, os.listdir says {v!r}"
           for k, v in sorted(want.items()) if got.get(k) != v]
    if bad:
        return False, ("%d of %d answers differ from CPython's:\n      %s"
                       % (len(bad), len(want), "\n      ".join(bad[:20])))
    if verbose:
        print(f"      {len(want)} listing answers identical to os.listdir/"
              f"os.walk")
    return True, ""


def run_case(case, arch, tmpdir, verbose):
    """(ok, detail) for one case on one architecture."""
    src = os.path.join(tmpdir, case.name + ".mojo")
    with open(src, "w") as f:
        f.write(case.source)
    out = os.path.join(tmpdir, case.name + "." + arch)
    rc, text = build(src, out, arch)
    if case.refusal:
        if rc == 0:
            return False, ("it BUILT. A base whose pointee is not established "
                           "must be refused: the blob path bounds-checks "
                           "against the byte at offset 0 of the pointer and "
                           "returns a number assembled out of it")
        if case.refusal not in text:
            return False, (f"refused, but the message does not name "
                           f"{case.refusal!r}: {text.strip()[-300:]}")
        if verbose:
            print(f"      refused with: {text.strip()[-160:]}")
        return True, ""
    if rc != 0:
        return False, f"build failed: {text.strip()[-400:]}"
    rc, stdout, stderr = run(out, arch)
    if rc != 0:
        return False, f"exit {rc}, stderr {stderr.strip()[:200]!r}"
    got = parse(stdout)
    want = case.expect
    if want is None and case.oracle is not None:
        want = case.oracle()
    if want is None:
        return False, "the case has neither `expect` nor an `oracle`"
    bad = [f"{k}: the image says {got.get(k)!r}, the expected answer is {v!r}"
           for k, v in want.items() if got.get(k) != v]
    if bad:
        return False, ("%d of %d answers wrong:\n      %s"
                       % (len(bad), len(want), "\n      ".join(bad)))
    if verbose:
        print(f"      {len(want)} answers correct")
    return True, ""


def build_stat_case(path, tmpdir):
    """A `Case` for one path, whose expectations CPython supplies."""
    # `@@PATH@@` and not `%s`: the program is full of `%d`, and a format
    # substitution over it would be reading those as conversions.
    src = STAT_PROGRAM.replace("@@PATH@@",
                               path.replace("\\", "\\\\").replace('"', '\\"'))
    return Case("stat_" + os.path.basename(path).replace(".", "_"),
                src, None, oracle=lambda: _stat_oracle(path),
                archs=["arm64"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset: " + ", ".join(
        c.name for c in CASES))
    args = ap.parse_args()

    archs = ["arm64"]
    r = rosetta()
    if r is True:
        archs.append("x86_64")
    elif r is None and args.verbose:
        print("NOTE: not Darwin, so the x86-64 image cannot be executed here; "
              "arm64 only")

    failed = []
    total = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = os.path.realpath(os.path.join(tmpdir, "fx"))
        os.makedirs(fixture)
        paths = make_shapes(fixture)
        cases = list(CASES)
        for shape, p in sorted(paths.items()):
            cases.append(build_stat_case(p, tmpdir))
        # A path that is not there at all, which is the sixth shape and the one
        # whose answer is a refusal rather than a mode.
        cases.append(build_stat_case(os.path.join(fixture, "no-such"),
                                     tmpdir))

        cases.append(Case("listdir_and_walk", "", None, archs=["arm64"]))
        names = args.cases or [c.name for c in cases]
        by_name = {c.name: c for c in cases}
        for n in names:
            if n not in by_name:
                print(f"ERROR: unknown case {n!r}", file=sys.stderr)
                return 2
        for n in names:
            case = by_name[n]
            if case.name == "listdir_and_walk":
                for arch in archs:
                    if arch not in (case.archs or archs):
                        print(f"SKIP {n} [{arch}]  (an `os` dylib that calls "
                              f"the C library is arm64-only on this backend: "
                              f"bugs/FORMAL_x86_64_dylib_with_an_extern_call_"
                              f"does_not_load.md)")
                        continue
                    total += 1
                    ok, detail = run_listdir_case(arch, tmpdir, fixture,
                                                  args.verbose)
                    print(("PASS " if ok else "FAIL ") + f"{n} [{arch}]" +
                          (("  " + detail) if detail else ""))
                    if not ok:
                        failed.append(f"{n}[{arch}]")
                continue
            for arch in archs:
                if case.archs is not None and arch not in case.archs:
                    print(f"SKIP {n} [{arch}]  (an `os` dylib that calls the C "
                          f"library is arm64-only on this backend: "
                          f"bugs/FORMAL_x86_64_dylib_with_an_extern_call_"
                          f"does_not_load.md)")
                    continue
                total += 1
                ok, detail = run_case(case, arch, tmpdir, args.verbose)
                print(("PASS " if ok else "FAIL ") + f"{n} [{arch}]" +
                      (("  " + detail) if detail else ""))
                if not ok:
                    failed.append(f"{n}[{arch}]")
    print(f"\n{total - len(failed)}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
