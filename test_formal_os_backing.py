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

# The record terminator, for the reason `test_formal_os.py` gives: a separator
# this suite can read back without asking whether the image decoded a literal,
# so a program here emits its records back to back and this is what separates
# them.
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
    the reason `test_formal_os.py` gives: a separator this file can read back
    without asking whether the image decoded a literal, `@@` being two bytes a
    real newline cannot collide with.
    """

    def __init__(self, name, source, expect=None, oracle=None, refusal=None,
                 archs=None, archs_reason=None, env=None):
        self.name = name
        self.source = source
        self.expect = expect
        self.oracle = oracle
        self.refusal = refusal
        # The ENVIRONMENT the image is started with, or None to inherit this
        # process's. It is a constructor argument and not an oracle fact
        # because of the one case that needs it: `os.environ`'s whole claim is
        # that it is populated from the real environment, so a case that reads
        # it has to know exactly which environment "the real" was. Inheriting
        # gives an answer that changes with the machine and with whatever ran
        # before — measured, and the difference is not small: this process's
        # `os.environ` and the `envp` block its child inherits disagreed by one
        # entry, because a shell adds `_` to the child's block and cannot add
        # it to a parent that has already started. A fixed dict answers that,
        # and a fixed dict can hold the shapes an inherited one cannot (a
        # variable set to the empty string, a value containing `=`).
        self.env = env
        # Which architectures this case can run on, or None for all of them, and
        # WHY when the list is short. The reason is a constructor argument and
        # not a sentence in the runner because this file used to carry ONE
        # reason for every skip, printed for all of them, and it was false:
        # "an `os` dylib that calls the C library is arm64-only on this
        # backend" (and a `bugs/` doc that does not exist). It was false in the
        # direction that hides defects — it is the only reason
        # `os.listdir` answered wrongly on x86-64 for as long as it did, because
        # the case that would have caught it was skipped for a fiction. An
        # `os`-importing program builds and RUNS under `arch -x86_64` on this
        # backend, measured: `os.getcwd` prints the right directory, and so do
        # `os.listdir` and every `os.path` field once the C names macOS spells
        # two ways bind to the right one (`model.target_libc_symbol`). One case
        # here is still arm64-only and says so with the refusal it hits.
        self.archs = archs
        self.archs_reason = archs_reason


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

# An augmented assignment THROUGH A SUBSCRIPT — the read-modify-write, which is
# a separate emitter from the plain-name one because the address has to be
# computed once and kept across the evaluation of both the element and the
# right-hand side. x86-64 used to REFUSE this outright
# (`augmented assignment target must be a plain name`), which made this case
# arm64-only and left the construct unpinned on one architecture;
# `formal/x86_64_codegen.py` now lowers it as `_emit_subscript_aug`, arm64's
# twin, so the `archs=["arm64"]` that documented the refusal is gone. The wider
# coverage of the construct — every operator, a byte element, a list element, an
# index that is a call — is in `test_formal_x86_64_parity.py`, which checks both
# architectures against CPython rather than against a constant written here.
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

# ── 2b. `listdir` as a PYTHON-LEVEL list ───────────────────────────────────
#
# The three shapes above read a blob through the module's own accessors,
# because that is what it published: `listdir` was declared `-> int` and a
# caller could do nothing else with the word. That was the half of
# `bugs/FORMAL_listdir_no_run_time_sequence.md` that was open, and it was a
# KIND and not a representation — the value has been one word pointing at
# `[count][element]…` since the blob landed. With `-> List[String]` on the
# declaration the annotation says so across the dylib boundary, and the three
# spellings a Python caller writes all lower:
#
#     len(names)        the count word at offset 0
#     names[i]          the element, as the element KIND the annotation gives
#     for x in names    a loop whose target is that element kind
#
# `n`, `chars` and `first` are the aggregate answers and `len`-through-the-
# accessor is the CONTROL: the same count read both ways, in one image, so a
# difference between them is a difference in how the kind was used rather than
# in what the filesystem said. The oracle is CPython's `os.listdir` of the same
# fixture, and its ORDER is the filesystem's `readdir` order, which is what
# both sides walk.
CASES.append(Case(
    "listdir_is_a_python_level_list",
    '''\
from os import listdir, listdir_len, listdir_free

def show(tag, p):
    names = listdir(p)
    printf("%s_n=%d@@", tag, len(names))
    printf("%s_acc=%d@@", tag, listdir_len(names))
    chars = 0
    for x in names:
        chars = chars + len(x)
    printf("%s_chars=%d@@", tag, chars)
    printf("%s_first=[%s]@@", tag, names[0])
    printf("%s_last=[%s]@@", tag, names[len(names) - 1])
    listdir_free(names)
    return 0


def main(n):
    show("root", "@@ROOT@@")
    show("dir", "@@ROOT@@/dir")
    return 0
''',
    None,
    oracle=lambda: _listdir_as_list_oracle(),
))


def _listdir_as_list_oracle():
    """CPython's answers for `listdir_is_a_python_level_list`.

    Computed against the SAME fixture the image walked, which is what makes the
    three aggregate answers comparable rather than merely equal: `chars` is the
    sum of `len(x)` over the same names, so a wrong element KIND shows up as a
    wrong sum rather than as a crash.

    **Only directories that EXIST**, and the reason is in the module rather than
    here: a missing path makes `listdir` answer the WORD 0 rather than a blob,
    and `len(0)` is a load at address 0 — a question about a null pointer, not
    about a directory listing. The 0-for-missing answer is `listdir_and_walk`'s
    row, through the accessors, which is where it belongs.
    """
    root = _FIXTURE[0]
    out = {}
    for tag, path in (("root", root), ("dir", os.path.join(root, "dir"))):
        names = os.listdir(path)
        out[f"{tag}_n"] = str(len(names))
        out[f"{tag}_acc"] = str(len(names))
        out[f"{tag}_chars"] = str(sum(len(x) for x in names))
        # The brackets are part of the RECORD, not of the value: the program
        # prints `[%s]` so an empty listing is visible as `[]` rather than as a
        # missing field, and the oracle strips them back off for the comparison.
        out[f"{tag}_first"] = f"[{names[0]}]"
        out[f"{tag}_last"] = f"[{names[-1]}]"
    return out


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


# ── 7. `os.environ`, against a FIXED process environment ───────────────────
#
# The fifth construct, and the only one whose answer is a fact about the host
# rather than about a file: the process environment. `formal/hostmods/os/
# __init__.mojo` reaches the `envp` block by asking the dynamic loader for the
# `environ` global at RUN time (`os/_syscalls.mojo`'s `fs_environ_vec`), so
# what has to be measured is that the block the kernel actually built is the
# block the view reports — the keys, the values, the ORDER, the count, and the
# two shapes an inherited environment cannot provide.
#
# **THE ENVIRONMENT IS FIXED, AND THAT IS THE POINT.** An inherited one cannot
# answer this: a shell adds `_` to a child's block and cannot add it to a parent
# that has already started, so this process's `os.environ` and the `envp` its
# child inherits are not the same dictionary — measured, one entry apart before
# any test code ran. A fixed dict makes the oracle exact, and it lets the case
# hold the two entries that separate a dict from a `getenv(3)` wrapper:
#
#   * `FORMAL_ENV_VIEW_EMPTY` set to the EMPTY STRING. Present, and not the same
#     as absent. `os.getenv` cannot tell those apart (both are `""`) and
#     `environ_get` can (0 against `""`), which is the whole reason the view is
#     a dict and not three functions.
#   * `FORMAL_ENV_VIEW_EQUALS` whose VALUE contains `=`. The split is at the
#     FIRST `=`, which is what `execve` says, so this is key
#     `FORMAL_ENV_VIEW_EQUALS` and value `a=b=c`.
#
# ORDER is compared, not just membership: the view walks `envp` in the order the
# block has, `subprocess` builds that block from this dict's iteration order,
# and CPython's `os.environ` keeps the order it was given. Two of the three
# moving and the third not would show up as a mismatch on `K0`.
#
# The `@@` in a value is replaced before it is printed, for the reason `REC`
# gives: a value that contained the terminator would split a record in half and
# the suite would report a disagreement that is really its own punctuation.
ENV_VIEW_ENV = {
    # Present on BOTH architectures and in this exact position on purpose.
    # `run_case` starts the x86-64 image through `arch -x86_64`, and a
    # TRANSLATED process is launched with `__CF_USER_TEXT_ENCODING` in its
    # environment whether the parent put it there or not — measured, arm64 with
    # `env -i` sees 0 variables and x86-64 with `env -i` sees this one. Putting
    # it in the fixed dict is what makes the two arms compare the SAME block:
    # the wrapper SETS the variable rather than appending a second one, so with
    # it declared both arms see exactly these entries in exactly this order.
    "__CF_USER_TEXT_ENCODING": "0x1F9:0x0:0x0",
    "FORMAL_ENV_VIEW_PLAIN": "one",
    "FORMAL_ENV_VIEW_EMPTY": "",
    "FORMAL_ENV_VIEW_EQUALS": "a=b=c",
    "FORMAL_ENV_VIEW_SPACE": "two words",
    "FORMAL_ENV_VIEW_TAIL": "last",
}

ENV_VIEW_PROGRAM = """\
from os import environ, environ_count, environ_key, environ_value
from os import environ_find, environ_get, environ_get_or, environ_has
from os import environ_set, environ_del, environ_items, environ_keys
from os import environ_copy, environ_pop, environ_clear, environ_update
from os import environ_popitem, environ_pair_free
from os import environ_free, getenv, putenv
from os._syscalls import str_replace_all

def show(s):
    return str_replace_all(s, "@@", "\\x01")


def main(n):
    var e = environ()
    var c = environ_count(e)
    printf("count %d@@", c)
    printf("start-has %d@@", environ_has(e, "FORMAL_ENV_VIEW_PROBE"))
    # EVERY key and value, in order: the whole claim of the view is that the
    # block the kernel built is the block this reports.
    var i = 0
    while i < c:
        printf("K%d [%s]@@", i, show(environ_key(e, i)))
        printf("V%d [%s]@@", i, show(environ_value(e, i)))
        i = i + 1
    # a key that is not there, through every spelling of "not there"
    printf("find-missing %d@@", environ_find(e, "FORMAL_ENV_VIEW_PROBE"))
    printf("has-missing %d@@", environ_has(e, "FORMAL_ENV_VIEW_PROBE"))
    printf("getor-missing [%s]@@",
           show(environ_get_or(e, "FORMAL_ENV_VIEW_PROBE", "dflt")))
    printf("del-missing %d@@", environ_del(e, "FORMAL_ENV_VIEW_PROBE"))
    # out of range in both directions
    printf("oob-key [%s]@@", show(environ_key(e, c)))
    printf("neg-value [%s]@@", show(environ_value(e, 0 - 1)))
    printf("items-is-view %d@@", environ_items(e) == e)
    printf("keys-vs-key %d@@", environ_keys(e, 0) == environ_key(e, 0))
    printf("keys-oob [%s]@@", show(environ_keys(e, c)))
    # `os.environ[k] = v` on a key that is not there: the blob grows and BOTH
    # answers move, because CPython's __setitem__ calls putenv.
    var e2 = environ_set(e, "FORMAL_ENV_VIEW_PROBE", "one")
    printf("set-new-count %d@@", environ_count(e2))
    printf("set-new-has %d@@", environ_has(e2, "FORMAL_ENV_VIEW_PROBE"))
    printf("set-new-get [%s]@@", show(environ_get(e2, "FORMAL_ENV_VIEW_PROBE")))
    printf("set-new-getenv [%s]@@", show(getenv("FORMAL_ENV_VIEW_PROBE")))
    # and on a key that is: the value is replaced, the count does not move
    var e3 = environ_set(e2, "FORMAL_ENV_VIEW_PROBE", "two")
    printf("set-same-count %d@@", environ_count(e3))
    printf("set-same-get [%s]@@", show(environ_get(e3, "FORMAL_ENV_VIEW_PROBE")))
    # `putenv` after the snapshot moves getenv and NOT the view, which is
    # CPython's own rule rather than a limitation of this one.
    printf("putenv %d@@", putenv("FORMAL_ENV_VIEW_LATE", "late"))
    printf("late-getenv [%s]@@", show(getenv("FORMAL_ENV_VIEW_LATE")))
    printf("late-view-has %d@@", environ_has(e3, "FORMAL_ENV_VIEW_LATE"))
    printf("late-view-get-is-0 %d@@",
           environ_get(e3, "FORMAL_ENV_VIEW_LATE") == 0)
    # `del os.environ[k]`: the pair goes and the variable goes
    printf("del %d@@", environ_del(e3, "FORMAL_ENV_VIEW_PROBE"))
    printf("del-count %d@@", environ_count(e3))
    printf("del-has %d@@", environ_has(e3, "FORMAL_ENV_VIEW_PROBE"))
    printf("del-getenv [%s]@@", show(getenv("FORMAL_ENV_VIEW_PROBE")))
    # the keys, at both ends, after the pair that was appended is gone
    printf("keys-0 [%s]@@", show(environ_keys(e3, 0)))
    printf("keys-last [%s]@@", show(environ_keys(e3, environ_count(e3) - 1)))
    # ── copy(): a DICT COPY, and the assertion is INDEPENDENCE ──
    # A copy that shared the original's buffers would answer every count and
    # every key below correctly and still be wrong: `environ_free` on either
    # blob would free what the other hands out. So the copy is written to and
    # the ORIGINAL is read back — which is the only way to see the two are two.
    var ec = environ_copy(e3)
    printf("copy-count %d@@", environ_count(ec))
    printf("copy-0 [%s]@@", show(environ_key(ec, 0)))
    printf("copy-last [%s]@@", show(environ_key(ec, environ_count(ec) - 1)))
    var ec2 = environ_set(ec, "FORMAL_ENV_VIEW_PLAIN", "written-in-copy")
    printf("copy-write [%s]@@", show(environ_get(ec2,
                                                 "FORMAL_ENV_VIEW_PLAIN")))
    printf("copy-original [%s]@@",
           show(environ_get(e3, "FORMAL_ENV_VIEW_PLAIN")))
    printf("copy-original-count %d@@", environ_count(e3))
    printf("free-copy %d@@", environ_free(ec2))
    # ── pop(k, default): the value outlives the pair ──
    # The pair goes through `environ_del`, so a pop that returned the alias
    # would hand back freed memory — and the count has to drop by one, which is
    # what says the removal happened at all rather than the value being copied
    # out and nothing removed.
    printf("pop [%s]@@", show(environ_pop(e3, "FORMAL_ENV_VIEW_PLAIN",
                                         "dflt")))
    printf("pop-count %d@@", environ_count(e3))
    printf("pop-has %d@@", environ_has(e3, "FORMAL_ENV_VIEW_PLAIN"))
    printf("pop-getenv [%s]@@", show(getenv("FORMAL_ENV_VIEW_PLAIN")))
    printf("pop-absent [%s]@@", show(environ_pop(e3, "FORMAL_ENV_VIEW_PROBE",
                                                "dflt")))
    printf("pop-absent-count %d@@", environ_count(e3))
    # ── popitem(): an ARBITRARY pair, as ONE blob ──
    # On a view the program BUILDS ITSELF from three known pairs, and that is the
    # whole reason: "which pair" is only decidable if the view's ORDER is known,
    # and a fresh `environ()` is a snapshot of a process environment the test
    # harness composed (`ENV_VIEW_ENV` plus whatever `putenv` added, and the
    # `…_LATE` above is one such) while `e3`'s order has been edited twice by the
    # removals above — `environ_del` shifts the LAST pair into the hole, which
    # `environ_pop`'s own docstring calls a recorded divergence rather than an
    # omission. A cleared view with three `environ_set` calls in it has neither
    # problem: the order is the three stores in that order, on both
    # architectures.
    #
    # Four things are being said at once, and the first is the point of the
    # function existing: the answer is ONE word — a blob's address — carrying
    # BOTH halves of the pair, which is what
    # `bugs/FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it.md` §4 called
    # "a genuine two-word limit" and is not. The second is that the count word
    # says how many elements the blob has, so a caller reads it by subscript
    # rather than trusting a convention. The third is that the removal happened:
    # the view is one pair shorter and `getenv` no longer sees the variable,
    # because CPython's `popitem` unsets it. The fourth is that the pair
    # OUTLIVES the view entry it came from — a copy, not the alias `environ_pop`
    # shows it must not be — and that it is released by its own release function.
    # `pair` is ANNOTATED, and that is not incidental: a subscript through an
    # unannotated word cannot read a buffer, which is the refusal this block
    # first hit and which `re.escape`'s own docstring records being measured
    # three ways.
    var ep = environ_copy(e3)
    environ_clear(ep)
    ep = environ_set(ep, "FORMAL_ENV_VIEW_TAIL", "last")
    ep = environ_set(ep, "FORMAL_ENV_VIEW_SPACE", "two words")
    ep = environ_set(ep, "FORMAL_ENV_VIEW_EQUALS", "a=b=c")
    var epn = environ_count(ep)
    var pair: Pointer[Int64] = environ_popitem(ep)
    printf("popitem-before %d@@", epn)
    printf("popitem-n %d@@", pair[0])
    printf("popitem-key [%s]@@", show(pair[1]))
    printf("popitem-value [%s]@@", show(pair[2]))
    printf("popitem-after %d@@", environ_count(ep))
    printf("popitem-getenv [%s]@@", show(getenv(pair[1])))
    printf("popitem-free %d@@", environ_pair_free(pair))
    printf("popitem-free-null %d@@", environ_pair_free(0))
    # An EMPTY view has no pair, and CPython raises KeyError for it: 0 is the
    # answer and a blob is never 0 on success, so `pair != 0` is the test.
    var eq = environ_copy(e3)
    environ_clear(eq)
    printf("popitem-empty %d@@", environ_popitem(eq))
    printf("popitem-null %d@@", environ_popitem(0))
    printf("popitem-empty-free %d@@", environ_free(eq))
    # ── update(other): every pair of the other view, in ONE call ──
    # Two views, both copies, so the rest of this program still has `e3`: the
    # receiver carries what `e3` carries and the other view changes ONE value
    # that is already there and adds ONE key that is not. Those are the two
    # branches of `environ_set` — in place, and append-and-maybe-move — and the
    # append is what makes `update`'s answer a blob rather than a status, which
    # is the whole contract `update-count-moved` is about.
    var ur = environ_copy(e3)
    var uo = environ_copy(e3)
    uo = environ_set(uo, "FORMAL_ENV_VIEW_PLAIN", "updated")
    uo = environ_set(uo, "FORMAL_ENV_VIEW_UPDATE_NEW", "added")
    var before = environ_count(ur)
    var u = environ_update(ur, uo)
    printf("update-count %d@@", environ_count(u))
    printf("update-count-before %d@@", before)
    # …and the count MOVED UP, which is what says the append happened rather
    # than the call being ignored: a `realloc` that does not move answers the
    # old pointer, and the caller cannot tell the two apart without this.
    printf("update-count-moved %d@@", environ_count(u) - before)
    printf("update-plain [%s]@@", show(environ_get(u, "FORMAL_ENV_VIEW_PLAIN")))
    printf("update-new-has %d@@", environ_has(u, "FORMAL_ENV_VIEW_UPDATE_NEW"))
    printf("update-new-get [%s]@@",
           show(environ_get(u, "FORMAL_ENV_VIEW_UPDATE_NEW")))
    printf("update-new-getenv [%s]@@",
           show(getenv("FORMAL_ENV_VIEW_UPDATE_NEW")))
    printf("update-kept [%s]@@", show(environ_get(u, "FORMAL_ENV_VIEW_TAIL")))
    # The SOURCE view is untouched, which is the same independence `copy()`
    # asserts and the reason `uo` is a copy rather than `e3` itself.
    printf("update-source [%s]@@", show(environ_get(uo,
                                                    "FORMAL_ENV_VIEW_PLAIN")))
    # `update(e, e)` — CPython allows `d.update(d)` and every pair is equal
    # afterwards, so this is the case that says the aliasing path duplicated the
    # value before handing it to a store that frees the buffer it was read
    # from. Read back through the view AFTER the call, because the failure this
    # row exists for is a freed buffer that still prints.
    var ua = environ_copy(u)
    ua = environ_update(ua, ua)
    printf("update-self-count %d@@", environ_count(ua))
    printf("update-self-plain [%s]@@",
           show(environ_get(ua, "FORMAL_ENV_VIEW_PLAIN")))
    printf("update-self-new [%s]@@",
           show(environ_get(ua, "FORMAL_ENV_VIEW_UPDATE_NEW")))
    printf("update-free %d@@", environ_free(ua))
    printf("update-free-other %d@@", environ_free(uo))
    printf("update-free-receiver %d@@", environ_free(u))
    # An EMPTY other view changes nothing and answers the receiver — CPython's
    # `update` of an empty mapping, and the 0-pair view is one this program
    # builds with `clear` rather than one it needs a second environment for.
    var ue = environ_copy(e3)
    environ_clear(ue)
    var ur2 = environ_copy(e3)
    var u2 = environ_update(ur2, ue)
    printf("update-empty-count %d@@", environ_count(u2))
    printf("update-empty-plain [%s]@@",
           show(environ_get(u2, "FORMAL_ENV_VIEW_TAIL")))
    printf("update-empty-free %d@@", environ_free(ue))
    printf("update-empty-free-receiver %d@@", environ_free(u2))
    # ── clear(): every pair, and every variable, gone ──
    # On a COPY, so the rest of this program still has a view to free — and
    # `clear-getenv` is the half a view-only implementation would miss: CPython
    # unsets each variable, so the C library stops seeing them too.
    var ed = environ_copy(e3)
    printf("clear %d@@", environ_clear(ed))
    printf("clear-count %d@@", environ_count(ed))
    printf("clear-getenv [%s]@@", show(getenv("FORMAL_ENV_VIEW_TAIL")))
    printf("clear-free %d@@", environ_free(ed))
    printf("clear-untouched %d@@", environ_count(e3))
    printf("free-view %d@@", environ_free(e3))
    return 0
"""


def _update_oracle():
    """CPython's `dict.update` answers for the `update` half of this program.

    Computed, not written out: the program builds two views out of copies of
    `e3`, changes one value that is already there and adds one key that is not,
    and then reads the receiver back. A dict in this process asked the same
    question is the oracle, because `os.environ.update` IS `MutableMapping.
    update` and the only thing a table written here would add is a second place
    for the two answers to disagree.

    `update-count-moved` is the one row that is about the CALL rather than the
    mapping: it is 1 because the added key made the view one pair longer, and
    the view is a `malloc`'d block that a `realloc` may move — which is why
    `environ_update` answers a blob and not a status.
    """
    recv = {k: v for k, v in ENV_VIEW_ENV.items()
            if k != "FORMAL_ENV_VIEW_PLAIN"}      # what `e3` holds at that point
    other = dict(recv)
    other["FORMAL_ENV_VIEW_PLAIN"] = "updated"
    other["FORMAL_ENV_VIEW_UPDATE_NEW"] = "added"
    n_before = len(recv)
    recv.update(other)                            # CPython's own operation
    recv.update(dict(recv))                       # `d.update(d)`: every pair equal
    # The EMPTY-other rows are about a DIFFERENT receiver: a fresh copy of `e3`,
    # which never had the two keys this block added. So they answer from the
    # count `e3` holds at that point — the six above less the one the `pop`
    # removed — and not from `recv`, which by now holds seven pairs. Saying so
    # here is cheaper than a reader working out which receiver a row is about.
    e3_count = len(ENV_VIEW_ENV) - 1
    return {
        "update-count": str(len(recv)),
        "update-count-before": str(n_before),
        "update-count-moved": str(len(recv) - n_before),
        "update-plain": f"[{recv['FORMAL_ENV_VIEW_PLAIN']}]",
        "update-new-has": "1",
        "update-new-get": f"[{recv['FORMAL_ENV_VIEW_UPDATE_NEW']}]",
        # `putenv`: the store went through `__setitem__`, so the C library
        # answers the new value too — the same fact `set-new-getenv` is.
        "update-new-getenv": f"[{recv['FORMAL_ENV_VIEW_UPDATE_NEW']}]",
        "update-kept": f"[{recv['FORMAL_ENV_VIEW_TAIL']}]",
        "update-source": "[updated]",
        "update-self-count": str(len(recv)),
        "update-self-plain": f"[{recv['FORMAL_ENV_VIEW_PLAIN']}]",
        "update-self-new": f"[{recv['FORMAL_ENV_VIEW_UPDATE_NEW']}]",
        "update-free": "0",
        "update-free-other": "0",
        "update-free-receiver": "0",
        "update-empty-count": str(e3_count),
        "update-empty-plain": f"[{ENV_VIEW_ENV['FORMAL_ENV_VIEW_TAIL']}]",
        "update-empty-free": "0",
        "update-empty-free-receiver": "0",
    }


def _popitem_oracle(items):
    """CPython's answers for the `popitem` block of `ENV_VIEW_PROGRAM`.

    **The one row that cannot be derived from `items` alone is the KEY**, and
    that is the honest answer rather than a missing one: CPython's `popitem` is
    documented as "remove and return an arbitrary (key, value) pair" and is LIFO
    since 3.7, so an oracle can only be written by RUNNING CPython's own
    `popitem` on the same mapping.  A table written out here would be a second
    place for the two answers to disagree, which is what every other oracle in
    this file is for.

    The mapping is the three-pair view the PROGRAM builds — a cleared view with
    three `environ_set` calls in it — and NOT `e3` and NOT the process
    environment, for the reason the block's own comment gives: `environ_del`
    reorders a view in place, so `e3`'s order is no longer `ENV_VIEW_ENV`'s, and
    the harness's environment is not the image's. A view whose order the program
    wrote down is the only one whose "which pair" is decidable.

    So the dict is asked, and every other row is read off what it answered:

      * `popitem-before` / `popitem-after` are the count either side of the call,
        so the row says the removal happened rather than the pair being copied
        out and nothing removed;
      * `popitem-n` is 2 because a container on this path keeps its count at word
        0 and this is a two-element blob — the same convention `environ_count`
        reads;
      * `popitem-getenv` is `[]`, not the value: `__delitem__` calls `unsetenv`,
        so the C library stops seeing the variable, which is the same fact
        `del-getenv` and `clear-getenv` are.
    """
    # The view the PROGRAM built: a cleared view with three `environ_set` calls
    # in it, in that order, so the order is the three stores in that order and
    # CPython is asked about exactly that mapping. Nothing here is derived from
    # the process environment the harness composed, which is the whole point —
    # see the block's own comment.
    env = {"FORMAL_ENV_VIEW_TAIL": "last",
           "FORMAL_ENV_VIEW_SPACE": "two words",
           "FORMAL_ENV_VIEW_EQUALS": "a=b=c"}
    before = len(env)
    d = dict(env)
    key, value = d.popitem()                      # CPython's own operation
    return {
        "popitem-before": str(before),
        "popitem-n": "2",
        "popitem-key": f"[{key}]",
        "popitem-value": f"[{value}]",
        "popitem-after": str(len(d)),
        "popitem-getenv": "[]",
        "popitem-free": "0",
        "popitem-free-null": "0",
        "popitem-empty": "0",
        "popitem-null": "0",
        "popitem-empty-free": "0",
    }


def _env_view_oracle():
    """CPython's answers for `ENV_VIEW_PROGRAM` over `ENV_VIEW_ENV`.

    The environment-dependent half is read off `ENV_VIEW_ENV` rather than off
    this process's `os.environ`, because `ENV_VIEW_ENV` is what the image is
    started with — see `ENV_VIEW_ENV`'s own comment for why those are not the
    same dictionary.

    The rest are CPython's answers about the operations, stated rather than
    derived, and each is a fact the case would otherwise only be able to check
    against the module:

      * `set-new-getenv` is `[one]` because `os.environ[k] = v` calls `putenv`,
        so `os.getenv(k)` answers the new value too;
      * `late-view-has` is 0 and `late-getenv` is `[late]` because
        `os.putenv` changes what `os.getenv` says and leaves `os.environ`
        holding what it held — the disagreement this module's `putenv`
        docstring is about, measured rather than described;
      * `del-getenv` is `[]` because `__delitem__` calls `unsetenv`;
      * `del-missing` is -1 where CPython raises `KeyError`, and
        `getor-missing` is the default where `os.environ.get(k, d)` would
        return it. Both are the recorded divergence, pinned.
    """
    items = list(ENV_VIEW_ENV.items())
    n = len(items)
    out = {
        "count": str(n),
        "start-has": "0",
        "find-missing": "-1",
        "has-missing": "0",
        "getor-missing": "[dflt]",
        "del-missing": "-1",
        "oob-key": "[]",
        "neg-value": "[]",
        "items-is-view": "1",
        "keys-vs-key": "1",
        "keys-oob": "[]",
        "set-new-count": str(n + 1),
        "set-new-has": "1",
        "set-new-get": "[one]",
        "set-new-getenv": "[one]",
        "set-same-count": str(n + 1),
        "set-same-get": "[two]",
        "putenv": "0",
        "late-getenv": "[late]",
        "late-view-has": "0",
        "late-view-get-is-0": "1",
        "del": "0",
        "del-count": str(n),
        "del-has": "0",
        "del-getenv": "[]",
        "keys-0": f"[{items[0][0]}]",
        "keys-last": f"[{items[-1][0]}]",
        # `copy()`: a dict copy holds the same pairs, so every count and key
        # above is the answer for the copy too, and the value written into it
        # is NOT the original's — which is what CPython's dict copy means and
        # what an aliasing copy would fail.
        "copy-count": str(n),
        "copy-0": f"[{items[0][0]}]",
        "copy-last": f"[{items[-1][0]}]",
        "copy-write": "[written-in-copy]",
        "copy-original": f"[{ENV_VIEW_ENV['FORMAL_ENV_VIEW_PLAIN']}]",
        "copy-original-count": str(n),
        "free-copy": "0",
        # `pop(k, default)`: CPython returns the value and the key is gone —
        # from the dict AND from `os.getenv`, because `__delitem__` unsets it.
        "pop": f"[{ENV_VIEW_ENV['FORMAL_ENV_VIEW_PLAIN']}]",
        "pop-count": str(n - 1),
        "pop-has": "0",
        "pop-getenv": "[]",
        "pop-absent": "[dflt]",
        "pop-absent-count": str(n - 1),
        # `update(other)`: computed with CPython's OWN `dict.update` over the
        # same starting mapping, because the point of these rows is that the
        # answer is a dict operation rather than a table written here. `recv` is
        # what `e3` holds at this point (every key but `…_PLAIN`, which the
        # `pop` above removed) and `other` is `recv` with one value replaced and
        # one key added — the in-place branch and the appending one.
        **_update_oracle(),
        # `popitem()`: CPython's own `dict.popitem` on the mapping the program
        # has at this point, for the reason `_popitem_oracle` gives.
        **_popitem_oracle(items),
        # `clear()`: the mapping is empty and every variable is unset, so
        # `os.getenv` — the C library's answer — is empty too.
        "clear": "0",
        "clear-count": "0",
        "clear-getenv": "[]",
        "clear-free": "0",
        "clear-untouched": str(n - 1),
        "free-view": "0",
    }
    for i, (k, v) in enumerate(items):
        out[f"K{i}"] = f"[{k}]"
        out[f"V{i}"] = f"[{v}]"
    return out


CASES.append(Case("environ_view", ENV_VIEW_PROGRAM, None,
                  oracle=_env_view_oracle, env=dict(ENV_VIEW_ENV)))


# ── 8. `os.environ`: a variable set to the EMPTY STRING, and an EMPTY view ──
#
# The other end of the same range, and the one that separates a dict from a
# `getenv(3)` wrapper. `environ_get` answers 0 for a key that is NOT there and
# `""` for a key that is there holding nothing, and those two are the same word
# through `os.getenv` — `formal/hostmods/os/__init__.mojo`'s `getenv`
# docstring says so and this is the case that would notice if it stopped being
# true.
#
# It also walks a view down to ZERO pairs, which is the smallest view there is
# and the only place `environ_keys(e, -1)` is asked of a real view rather than
# of an index past the end.
#
# `__CF_USER_TEXT_ENCODING` is here for the reason `ENV_VIEW_ENV` gives, and it
# carries `arch`'s own value: a translated process OVERWRITES that variable
# rather than adding one, so passing it empty is not the way to get an empty
# value — measured, arm64 answered `[]` and x86-64 answered
# `[0x1F9:0x0:0x0]` for the same dict. `ENV_VIEW_ENV`'s value is the one that
# makes the two arms agree.
ENV_VIEW_EMPTY_ENV = {
    "__CF_USER_TEXT_ENCODING": "0x1F9:0x0:0x0",
    "FORMAL_ENV_VIEW_EMPTY": "",
}

ENV_VIEW_EMPTY_PROGRAM = """\
from os import environ, environ_count, environ_key, environ_value
from os import environ_has, environ_get, environ_set, environ_del
from os import environ_keys, environ_free

NAME = "FORMAL_ENV_VIEW_EMPTY"
ABSENT = "FORMAL_ENV_VIEW_ABSENT"

def main(n):
    var e = environ()
    var c = environ_count(e)
    printf("count %d@@", c)
    printf("empty-has %d@@", environ_has(e, NAME))
    printf("empty-get [%s]@@", environ_get(e, NAME))
    # THE CASE: present-and-empty is NOT absent, and the two are different
    # words.
    printf("empty-get-is-0 %d@@", environ_get(e, NAME) == 0)
    printf("absent-has %d@@", environ_has(e, ABSENT))
    printf("absent-get-is-0 %d@@", environ_get(e, ABSENT) == 0)
    printf("keys-0 [%s]@@", environ_keys(e, 0))
    printf("keys-last [%s]@@", environ_keys(e, c - 1))
    # overwriting a key that IS there replaces the value and leaves the count
    var e2 = environ_set(e, NAME, "x")
    printf("set-same-count %d@@", environ_count(e2))
    printf("set-same-get [%s]@@", environ_get(e2, NAME))
    # and `del` walks the view down to nothing
    printf("del-empty %d@@", environ_del(e2, NAME))
    printf("del-empty-count %d@@", environ_count(e2))
    printf("del-cf %d@@", environ_del(e2, "__CF_USER_TEXT_ENCODING"))
    printf("del-count %d@@", environ_count(e2))
    printf("del-has %d@@", environ_has(e2, NAME))
    printf("keys-empty [%s]@@", environ_keys(e2, 0))
    printf("keys-neg [%s]@@", environ_keys(e2, 0 - 1))
    printf("free %d@@", environ_free(e2))
    return 0
"""


def _env_view_empty_oracle():
    """CPython's answers for a two-variable environment, one of them empty.

    `empty-get-is-0` is 0 and `absent-get-is-0` is 1, and that pair is the whole
    case: `os.environ[NAME]` is `""` and `os.environ.get(ABSENT)` is `None`, so
    an implementation that answered both with the same word could not tell them
    apart — which is exactly what `os.getenv` cannot do either, and why this is
    the case rather than one more lookup in the case above.
    """
    return {
        "count": "2",
        "empty-has": "1",
        "empty-get": "[]",
        "empty-get-is-0": "0",
        "absent-has": "0",
        "absent-get-is-0": "1",
        "keys-0": "[__CF_USER_TEXT_ENCODING]",
        "keys-last": "[FORMAL_ENV_VIEW_EMPTY]",
        "set-same-count": "2",
        "set-same-get": "[x]",
        "del-empty": "0",
        "del-empty-count": "1",
        "del-cf": "0",
        "del-count": "0",
        "del-has": "0",
        "keys-empty": "[]",
        "keys-neg": "[]",
        "free": "0",
    }


CASES.append(Case("environ_view_empty", ENV_VIEW_EMPTY_PROGRAM, None,
                  oracle=_env_view_empty_oracle,
                  env=dict(ENV_VIEW_EMPTY_ENV)))


def build(src, out, arch):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "--backend=" + arch, "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(out, arch, env=None):
    """`(rc, stdout, stderr)` for one image, a HANG reported rather than raised.

    A timeout is a FAILURE of the case, not of the suite: a formal image that
    never terminates is one of the wrong answers this file exists to catch, and
    the way it showed up before was `subprocess.TimeoutExpired` escaping `main`
    and taking the remaining twenty-odd cases with it — so the one case that
    hangs is reported and every other case still runs. `rc` is the shell's
    timeout convention (124) and stderr names the timeout, so the caller sees a
    case that failed with a reason rather than a case that vanished.

    `env` replaces the environment the image starts with; `None` inherits this
    process's, which is what every case but `environ_view` wants. It is the
    CHILD's block either way: `arch` on the x86-64 arm is resolved in this
    process, so a case with a minimal `env` still finds it.
    """
    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", out]        # Rosetta 2
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return 124, "", f"the image did not finish within {RUN_TIMEOUT}s"
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


# The fixture root, for the oracle of a case whose program names `@@ROOT@@`.
# A one-element list because the oracle is a zero-argument callable (the `Case`
# contract) and the fixture only exists inside `main`'s `TemporaryDirectory`.
_FIXTURE = [""]


def run_case(case, arch, tmpdir, verbose, fixture=None):
    """(ok, detail) for one case on one architecture.

    `@@ROOT@@` is the fixture directory every case's source may name, so a case
    can ask a question about a directory whose contents it did not write. The
    convention is `LISTDIR_PROGRAM`'s own, generalised from it: a case that does
    not mention the marker is unaffected, and one that does gets the same
    `run_listdir_case` does.
    """
    src = os.path.join(tmpdir, case.name + ".mojo")
    with open(src, "w") as f:
        f.write(case.source.replace("@@ROOT@@", fixture)
                if fixture else case.source)
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
    rc, stdout, stderr = run(out, arch, case.env)
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
                src, None, oracle=lambda: _stat_oracle(path))


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
        _FIXTURE[0] = fixture
        paths = make_shapes(fixture)
        cases = list(CASES)
        for shape, p in sorted(paths.items()):
            cases.append(build_stat_case(p, tmpdir))
        # A path that is not there at all, which is the sixth shape and the one
        # whose answer is a refusal rather than a mode.
        cases.append(build_stat_case(os.path.join(fixture, "no-such"),
                                     tmpdir))

        cases.append(Case("listdir_and_walk", ""))
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
                        print(f"SKIP {n} [{arch}]  ({case.archs_reason})")
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
                    print(f"SKIP {n} [{arch}]  ({case.archs_reason})")
                    continue
                total += 1
                ok, detail = run_case(case, arch, tmpdir, args.verbose,
                                      fixture)
                print(("PASS " if ok else "FAIL ") + f"{n} [{arch}]" +
                      (("  " + detail) if detail else ""))
                if not ok:
                    failed.append(f"{n}[{arch}]")
    print(f"\n{total - len(failed)}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
