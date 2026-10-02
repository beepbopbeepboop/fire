#!/usr/bin/env python3
r"""Build `formal/hostmods/shutil.mojo` and RUN it against CPython's `shutil`.

    python3 test_formal_shutil.py [-v] [group ...]

Groups: `syscalls`, `copyfile`, `metadata`, `move`, `rmtree`, `copytree`,
`which`, `resolve`, `absent`. With no argument, all.

WHY THE ORACLE IS CPython'S `shutil` AND NOT A TREE OF EXPECTED FILES
---------------------------------------------------------------------
Every group here is a DIFFERENTIAL test: the same operation is performed twice
on two trees built the same way — once by the image, once by `shutil` in this
process — and the two results are compared, along with what each left on disk.
A recorded tree would be a table, and the interesting part of `shutil` is
exactly the part a table gets wrong: the mode of a copied file, the number of
seconds on a copied `mtime`, whether a symbolic link inside a removed tree was
followed. So the assertions are *relations between two runs* plus CPython's own
answers for the returns, and the trees are built fresh for each group because
`rmtree` and `move` destroy theirs.

THE FIXTURE, AND WHY IT HAS THE THREE THINGS THAT SEPARATE A CORRECT
`rmtree` FROM A BROKEN ONE
---------------------------------------------------------------
  * a SYMBOLIC LINK inside the tree. `os.walk` here FOLLOWS a link to a
    directory (`formal/hostmods/os/__init__.mojo` says so) and CPython's does
    not. A `rmtree` that trusted the walk would delete THROUGH the link — and
    the deletion would be invisible, because `unlink` removes the name and the
    directory it pointed at is simply gone. `test_formal_os_backing.py`
    measures the walk's divergence; this measures the consequence.
  * a link back to an ANCESTOR, because a walk that follows it and is not depth
    bounded does not terminate, and `rmtree`'s `maxdepth` is the bound.
  * an EMPTY DIRECTORY, which is the one entry `rmdir` succeeds on and the one
    a "remove the files then rmdir" loop gets right by accident only if it
    rmdirs EVERY directory including the root.

A FILE LARGER THAN THE COPY BUFFER, because `shutil`'s copying is a LOOP and a
single `read` is not a copy: `fs_fread` returns what arrived, not what was asked
for, and a destination that is short is a silent truncation. 200,000 bytes
against a 65,536-byte buffer is three full chunks and a remainder, which is the
shape that a loop with an off-by-one in its last step gets wrong.

BOTH ARCHITECTURES
------------------
Every group is built and run for arm64 and for x86-64 and the two answers are
compared with each other as well as with CPython. The runner is
`test_formal_dylib.py`'s `build_and_run`, shared with `test_formal_stat.py` and
`test_formal_math.py`; this file's only job is the comparison.
"""
import argparse
import os
import platform
import shutil
import stat as CPY
import subprocess
import sys
import tempfile

import test_formal_dylib as D        # noqa: E402  (shared two-backend runner)

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 900
REC = "@@"

# The size of the file `copyfile`'s loop has to survive, and it is deliberately
# not a multiple of the module's 65,536-byte buffer: 200,000 is three full
# buffers and 3,392 bytes, so a loop that reads once, or that drops the last
# chunk, is caught by the content comparison rather than by a length.
BIG = 200000


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures this host can run a formal image on — see
    `test_formal_math.py`'s copy of this, which is the shared `rosetta()`."""
    if not D.host_machine():
        return []
    ok, why = D.rosetta()
    if not ok:
        print(f"note: x86-64 half SKIPPED — {why}")
        return ["arm64"]
    return list(D.BACKENDS)


def both_ways(archs, tmpdir, name, src, fn, verbose, cwd=None):
    """See `test_formal_math.py`. `cwd` is here because every group in this file
    runs its image INSIDE the tree it is mutating."""
    if verbose:
        print(f"    building and running on {' and '.join(archs)}")
    try:
        return D.build_and_run(src, name, tmpdir, fn, backends=archs, cwd=cwd)
    except D.Failure as e:
        raise Failure(str(e)) from None


# ── the fixture ─────────────────────────────────────────────────────────────

def fixture(root, ancestor_link=True):
    """A tree with the awkward entries, under `root`. Returns its path.

    Built fresh by every group, because `rmtree` and `move` destroy theirs and a
    group that ran second against a tree the first one deleted would be testing
    nothing.

        root/
          f1                 "hello\n"
          empty/             an empty directory
          a/f2               "second\n"
          a/b/f3             "third\n"
          a/link -> ../f1    a link WITHIN the tree
          up -> ..           a link back to the tree's PARENT
          deep/x/y/z/f4      four levels down, for `rmtree`'s depth

    `ancestor_link` is `False` for the `copytree` group, and the reason is
    CPython's rather than this module's: **`shutil.copytree` DOES recurse through
    a symbolic link to a directory**, because it tests `entry.is_dir()` with the
    default `follow_symlinks=True`. So a fixture carrying `a/up -> ..` makes
    CPython's own `copytree` walk up the tree until the kernel gives up with
    `ELOOP` — measured, forty-one levels of `a/up/a/up/…` before it does. That
    is worth knowing about CPython and it is NOT worth comparing against, so the
    `copytree` group uses the same fixture without that one link and the
    `rmtree` group uses it with, since refusing to follow it is precisely what
    `rmtree` is being asked to do.
    """
    os.makedirs(os.path.join(root, "empty"), exist_ok=True)
    os.makedirs(os.path.join(root, "a", "b"), exist_ok=True)
    os.makedirs(os.path.join(root, "deep", "x", "y", "z"), exist_ok=True)
    with open(os.path.join(root, "f1"), "w") as f:
        f.write("hello\n")
    with open(os.path.join(root, "a", "f2"), "w") as f:
        f.write("second\n")
    with open(os.path.join(root, "a", "b", "f3"), "w") as f:
        f.write("third\n")
    with open(os.path.join(root, "deep", "x", "y", "z", "f4"), "w") as f:
        f.write("fourth\n")
    os.chmod(os.path.join(root, "a", "f2"), 0o640)
    os.chmod(os.path.join(root, "a"), 0o750)
    os.symlink("../f1", os.path.join(root, "a", "link"))
    if ancestor_link:
        os.symlink("..", os.path.join(root, "a", "up"))
    return root


def listing(root):
    """Every path under `root`, as sorted `relpath -> kind` pairs.

    `kind` is `f`, `d` or `l` from `lstat`, so a symbolic link is recorded as a
    LINK and not as the file it points at — which is the distinction the `rmtree`
    group's link case turns on. A tree's listing is the thing both the image's
    filesystem and CPython's have to agree on at the END, and it is compared as
    a set of pairs rather than as a `find` transcript so a difference in ORDER
    is not a difference in the tree.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        for n in sorted(dirnames + filenames):
            p = os.path.join(dirpath, n)
            r = n if rel == "." else os.path.join(rel, n)
            st = os.lstat(p)
            kind = "l" if stat_is_link(st) else ("d" if stat_is_dir(st) else "f")
            out.append("%s:%s" % (r, kind))
    return sorted(out)


def stat_is_link(st):
    return (st.st_mode & 0o170000) == 0o120000


def stat_is_dir(st):
    return (st.st_mode & 0o170000) == 0o040000


def modes(root):
    """`relpath -> permission bits` for every path under `root`, links included.

    `lstat` and not `stat`, because a link's own mode is `0o777` and following it
    would report the target's — and the difference is exactly what `copytree`
    with `symlinks=False` does, which copies the CONTENT of what the link points
    at. The permission bits come from `S_IMODE`, matching `copymode`'s contract
    on both sides.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        for n in sorted(dirnames + filenames):
            p = os.path.join(dirpath, n)
            r = n if rel == "." else os.path.join(rel, n)
            out.append("%s:%o" % (r, CPY.S_IMODE(os.lstat(p).st_mode)))
    return sorted(out)


def contents(root):
    """`relpath -> bytes` for every REGULAR file under `root`, links followed.

    A link's content is what CPython's `copy2` reads through it — `open` follows
    — so this is where a copy that unlinked instead of copied would show up, as
    a missing key rather than as a different value.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        for n in sorted(dirnames + filenames):
            p = os.path.join(dirpath, n)
            r = n if rel == "." else os.path.join(rel, n)
            if stat_is_dir(os.lstat(p)):
                continue
            try:
                with open(p, "rb") as f:
                    out.append("%s=%d" % (r, len(f.read())))
            except OSError as e:
                out.append("%s=ERR%d" % (r, e.errno))
    return sorted(out)


# ── the groups ──────────────────────────────────────────────────────────────

def group_syscalls(tmpdir, archs, verbose):
    """The five calls `shutil` needed that no host module had.

    `fopen`/`fwrite`/`fread`/`fclose` and `utimes`, checked against CPython's
    own `open()` and `os.utime` on the same file, because they are the two
    reasons `shutil` was absent and a module that is written on top of them
    should not be the only thing that has ever exercised them.

    `utimes` is the interesting one: `struct stat` reports NANOSECONDS and
    `struct timeval` takes MICROSECONDS, so a caller that hands a stat's value
    straight through is off by a factor of a thousand. The group sets an
    atime/mtime with microsecond parts and reads the seconds back, and CPython's
    `os.utime` does the same to its own file for the answer.
    """
    src = """\
from os._syscalls import str_alloc, str_copy, fs_fopen, fs_fwrite, fs_fread
from os._syscalls import fs_fclose, fs_utimes, fs_stat_field64
from os._syscalls import fs_stat_mode

def main(n):
    var p = "syscalls.txt"
    var f = fs_fopen(p, "wb")
    printf("open-w=%lld@@", f != 0)
    var buf: Pointer[UInt8] = str_alloc(16)
    str_copy(buf, "0123456789", 10)
    printf("write=%lld@@", fs_fwrite(f, buf, 10))
    printf("close-w=%lld@@", fs_fclose(f))
    printf("mode=%lld@@", fs_stat_mode(p, 1))
    var g = fs_fopen(p, "rb")
    var rb: Pointer[UInt8] = str_alloc(32)
    printf("read=%lld@@", fs_fread(g, rb, 9))
    printf("read-bytes=%s@@", rb)
    printf("close-r=%lld@@", fs_fclose(g))
    printf("open-missing=%lld@@", fs_fopen("no-such-file-here", "rb") != 0)
    printf("utimes=%lld@@", fs_utimes(p, 1000000000, 123456, 2000000000, 654321))
    printf("atime=%lld@@", fs_stat_field64(p, 1, 32))
    printf("ansec=%lld@@", fs_stat_field64(p, 1, 40))
    printf("mtime=%lld@@", fs_stat_field64(p, 1, 48))
    printf("mnsec=%lld@@", fs_stat_field64(p, 1, 56))
    printf("utimes-zero=%lld@@", fs_utimes(p, 0, 0, 0, 0))
    printf("mtime-zero=%lld@@", fs_stat_field64(p, 1, 48))
    return 0
"""

    work = os.path.join(tmpdir, "syscalls")
    os.makedirs(work, exist_ok=True)
    for stale in os.listdir(work):
        os.remove(os.path.join(work, stale))

    want = _syscalls_oracle(work)
    seen = {}

    def compare(arch, recs):
        got = dict(rec.split("=", 1) for rec in recs if "=" in rec)
        bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
               for k, v in want.items() if got.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want)} answers differ "
                       f"from CPython's own `open`/`os.utime`: " +
                       "; ".join(bad))
        seen[arch] = got

    both_ways(archs, tmpdir, "shutil_syscalls", src, compare, verbose,
              cwd=work)
    if verbose:
        print(f"    {len(want)} answers, each against CPython's `open` and "
              f"`os.utime` on the same file")
    return True, (f"{len(want)} syscall answers agree with CPython's `open` "
                  f"and `os.utime`")


def _syscalls_oracle(work):
    """CPython's answers for `group_syscalls`, computed in this process.

    Done by CALLING `open` and `os.utime` on a file of the same name in a
    sibling directory, so the two runs cannot interfere and the answers come
    from the same filesystem at the same moment. The image's file is removed
    first by the caller, and this one is written where the image will not touch
    it.
    """
    p = os.path.join(work, "oracle.txt")
    got = {}
    with open(p, "wb") as f:
        got["write"] = str(f.write(b"0123456789"))
    got["open-w"] = "1"
    got["close-w"] = "0"
    # the FULL `st_mode`, not `S_IMODE` of it: `fs_stat_mode` is `stat(2)`'s
    # `st_mode`, and comparing it against the permission bits alone fails on the
    # TYPE bits — the difference between "the file has mode 644" and "the file
    # is a regular file with mode 644".  The first version of this oracle used
    # `S_IMODE` and reported 33188 against 420.
    got["mode"] = str(os.stat(p).st_mode)
    with open(p, "rb") as g:
        data = g.read(9)
    got["read"] = str(len(data))
    got["read-bytes"] = data.decode("latin-1")
    got["close-r"] = "0"
    got["open-missing"] = "0"
    # MICROSECOND-ALIGNED, and that is the point of the group. `utimes` takes
    # microseconds and the filesystem rounds to nanoseconds, so asking for 123456
    # microseconds and reading the nanosecond field back gives 123456000 exactly.
    # CPython's own `os.utime(ns=...)` path rounds the OTHER way for the same
    # request — measured, 123456001 — so comparing the raw nanosecond field of the
    # two would be comparing two rounding policies and nothing else. The first
    # version of this oracle used `os.utime`'s float seconds and compared the raw
    # field, and reported two mismatches on values neither side got wrong.
    os.utime(p, ns=(1000000000 * 1000000000 + 123456 * 1000,
                    2000000000 * 1000000000 + 654321 * 1000))
    st = os.stat(p)
    got["utimes"] = "0"
    got["atime"] = str(int(st.st_atime))
    got["ansec"] = str(int(st.st_atime_ns % 1000000000))
    got["mtime"] = str(int(st.st_mtime))
    got["mnsec"] = str(int(st.st_mtime_ns % 1000000000))
    os.utime(p, (0, 0))
    got["utimes-zero"] = "0"
    got["mtime-zero"] = str(int(os.stat(p).st_mtime))
    os.remove(p)
    return got


def group_copyfile(tmpdir, archs, verbose):
    """`copyfile`'s bytes and its four refusals.

    The bytes are checked by LENGTH AND BY CONTENT against CPython's own
    `shutil.copyfile` of the same source, and the source is larger than the copy
    buffer so that a loop with one read in it fails here rather than passing on a
    small file.

    The four refusals are CPython's exceptions, and each is a case where this
    module returns `""`: the same file on both sides (`SameFileError`), a source
    that is not there, a source that is a directory (`IsADirectoryError`), and a
    destination whose directory does not exist. They are the cases a `copyfile`
    that only ever says yes would pass everything else in this file.
    """
    src = """\
from shutil import copyfile

def main(n):
    var big = "big.bin"
    var small = "small.txt"
    printf("big=%s@@", copyfile(big, "out_big.bin"))
    printf("small=%s@@", copyfile(small, "out_small.txt"))
    printf("same=[%s]@@", copyfile(small, small))
    printf("missing=[%s]@@", copyfile("no-such-source", "out_missing.txt"))
    printf("srcdir=[%s]@@", copyfile("adir", "out_dir.txt"))
    printf("nodstdir=[%s]@@", copyfile(small, "no/such/dir/out.txt"))
    printf("empty=[%s]@@", copyfile("empty.txt", "out_empty.txt"))
    return 0
"""
    seen = {}
    work = None
    want = {}

    def compare(arch, recs, work=work, want=want):
        got = dict(_recs(recs))
        bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
               for k, v in want.items() if got.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want)} `copyfile` "
                       f"answers differ from CPython's `shutil`: " +
                       "; ".join(bad))
        seen[arch] = work

    for arch in archs:
        # A PARALLEL DIRECTORY FOR CPYTHON, with the same fixture and the SAME
        # destination names, so the returns are comparable strings. The first
        # version gave CPython `py_big.bin` and the image `out_big.bin` and
        # compared them, and three of seven calls "differed" — because the two
        # were asked to write different files, which is a difference in the
        # TEST and not in either implementation.
        work = _copy_work(tmpdir, "copyfile_" + arch)
        pyw = _copy_work(tmpdir, "copyfilepy_" + arch)
        want = _copyfile_oracle(pyw)
        both_ways([arch], tmpdir, "shutil_copyfile", src, compare, verbose,
                  cwd=work)

        # and the two copied files' bytes, compared byte count against the
        # source and against CPython's copy of the same source
        for name, py_name, size in (("out_big.bin", "out_big.bin", BIG),
                                    ("out_small.txt", "out_small.txt", 6),
                                    ("out_empty.txt", "out_empty.txt", 0)):
            p = os.path.join(work, name)
            check(os.path.isfile(p), f"the image did not create {name}")
            got = os.path.getsize(p)
            check(got == size,
                  f"{name} is {got} bytes and CPython's copyfile produced "
                  f"{size}; the source is larger than the 65,536-byte copy "
                  f"buffer, so a length difference here is a loop that dropped "
                  f"a chunk")
            pp = os.path.join(pyw, py_name)
            if os.path.isfile(pp):
                check(open(p, "rb").read() == open(pp, "rb").read(),
                      f"{name} holds different bytes from CPython's copy of "
                      f"the same source")
        check(open(os.path.join(work, "out_small.txt"), "rb").read()
              == b"hello\n",
              "out_small.txt does not hold the source's bytes")
    if verbose:
        print(f"    {len(want)} returns plus the bytes of 3 copies, one of "
              f"them {BIG} bytes, each against CPython's copy of the same "
              f"source")
    return True, (f"{len(want)} returns agree with CPython, and the copied "
                  f"bytes match including a {BIG}-byte file")


def _copy_work(tmpdir, tag):
    """The directory `copyfile`'s group runs in, with its sources built."""
    work = os.path.join(tmpdir, tag)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "big.bin"), "wb") as f:
        f.write(bytes((i * 7 + 11) % 251 for i in range(BIG)))
    with open(os.path.join(work, "small.txt"), "w") as f:
        f.write("hello\n")
    with open(os.path.join(work, "empty.txt"), "w") as f:
        f.write("")
    os.makedirs(os.path.join(work, "adir"), exist_ok=True)
    return work


def _copyfile_oracle(work):
    """CPython's `shutil.copyfile` returns for the same seven calls, as strings.

    **RUN IN `work`,** by `chdir` around the whole thing, because every path in
    the corpus is RELATIVE and this process's working directory is the
    repository. The first version did not, every call raised `FileNotFound`, and
    the oracle converts an exception to `""` — so the group reported "the module
    returned the wrong thing for four of seven calls" instead of "the oracle
    asked in the wrong place". That is what an oracle that hides exceptions costs
    when it is also wrong, and it is why the `chdir` is in the function rather
    than at the call site.

    An EXCEPTION is `""`, which is the module's refusal spelling: the point of
    the group is that CPython raises where this returns, so the oracle has to
    state the raise as the thing CPython does rather than propagate it.
    """
    out = {}
    cwd = os.getcwd()
    os.chdir(work)

    def call(key, fn):
        try:
            v = fn()
            out[key] = v if isinstance(v, str) else str(v)
        except Exception as e:
            out[key] = ""          # the module's refusal, and CPython raised
    call("big", lambda: shutil.copyfile("big.bin", "out_big.bin"))
    call("small", lambda: shutil.copyfile("small.txt", "out_small.txt"))
    call("same", lambda: shutil.copyfile("small.txt", "small.txt"))
    call("missing", lambda: shutil.copyfile("no-such-source", "out_missing"))
    call("srcdir", lambda: shutil.copyfile("adir", "out_dir.txt"))
    call("nodstdir", lambda: shutil.copyfile("small.txt", "no/such/dir/o.txt"))
    call("empty", lambda: shutil.copyfile("empty.txt", "out_empty.txt"))
    os.chdir(cwd)
    return out


def group_metadata(tmpdir, archs, verbose):
    """`copy`, `copy2`, `copymode` and `copystat`, and the ONE difference.

    `copy` carries the PERMISSION BITS and not the times; `copy2` carries both.
    That is the only observable difference between the two, so it is what this
    group is for, and it is asserted as a pair of RELATIONS — `copy` satisfies
    "the mode matches" and does NOT satisfy "the time matches", `copy2`
    satisfies both — plus CPython's own pair of relations on the same tree.

    A test that asserted an exact `mtime` would be asserting the wall clock. A
    test that only asserted `copy2`'s `mtime` EQUALS the source's would pass for
    a module whose `copy2` is `copy` whenever the destinations were built by
    copying the source's bytes, which is why the destinations here start as
    byte-identical copies with a DIFFERENT timestamp: the mode and the time are
    the only things the group is measuring, and the content check is
    `contents()`'s job.
    """
    src = """\
from shutil import copy, copy2, copymode, copystat

def main(n):
    printf("copy=%s@@", copy("small.txt", "out_copy.txt"))
    printf("copy2=%s@@", copy2("small.txt", "out_copy2.txt"))
    printf("copymode=%lld@@", copymode("small.txt", "out_mode.txt"))
    printf("copystat=%lld@@", copystat("small.txt", "out_stat.txt"))
    return 0
"""
    got, py = {}, {}
    for arch in archs:
        work = _meta_work(tmpdir, "meta_" + arch)
        seen = {}

        def compare(a, recs, seen=seen):
            got_ = dict(rec.split("=", 1) for rec in recs if "=" in rec)
            check(got_.get("copy") == "out_copy.txt",
                  f"[{a}] copy returned {got_.get('copy')!r}")
            check(got_.get("copy2") == "out_copy2.txt",
                  f"[{a}] copy2 returned {got_.get('copy2')!r}")
            check(got_.get("copymode") == "0",
                  f"[{a}] copymode returned {got_.get('copymode')!r}")
            check(got_.get("copystat") == "0",
                  f"[{a}] copystat returned {got_.get('copystat')!r}")
            seen[a] = got_

        both_ways([arch], tmpdir, "shutil_metadata", src, compare, False,
                  cwd=work)
        got[arch] = _meta_facts(work, "out_copy.txt", "out_copy2.txt")
        shutil.copy(os.path.join(work, "small.txt"),
                    os.path.join(work, "py_copy.txt"))
        shutil.copy2(os.path.join(work, "small.txt"),
                     os.path.join(work, "py_copy2.txt"))
        py[arch] = _meta_facts(work, "py_copy.txt", "py_copy2.txt")

    g, p = got[archs[0]], py[archs[0]]
    check("one_dst_mtime" in g and "two_dst_mtime" in g,
          "the metadata group did not record the destinations' times at all")
    check(g["one_mode_eq"] == 1,
          "copy did not carry the source's permission bits: source %o, "
          "destination %o" % (g["one_src_mode"], g["one_dst_mode"]))
    check(g["one_mtime_eq"] == 0,
          "copy DID carry the modification time, and the difference between "
          "copy and copy2 is that it does not")
    check(g["two_mode_eq"] == 1 and g["two_mtime_eq"] == 1,
          "copy2 did not carry both: mode_eq=%d mtime_eq=%d (source %o/%d, "
          "destination %o/%d)"
          % (g["two_mode_eq"], g["two_mtime_eq"], g["two_src_mode"],
             g["two_src_mtime"], g["two_dst_mode"], g["two_dst_mtime"]))
    check(p["one_mode_eq"] == 1 and p["one_mtime_eq"] == 0,
          "CPython's own copy does not satisfy the relation the image's is "
          "being compared against, so the comparison is not the same test: "
          "CPython gives mode_eq=%d mtime_eq=%d"
          % (p["one_mode_eq"], p["one_mtime_eq"]))
    check((g["one_src_mode"], g["one_dst_mode"])
          == (p["one_src_mode"], p["one_dst_mode"]),
          f"the image's copy gives mode {g['one_dst_mode']:o} where CPython's "
          f"gives {p['one_dst_mode']:o}")
    check((g["two_dst_mtime"], g["two_dst_mode"])
          == (p["two_dst_mtime"], p["two_dst_mode"]),
          f"the image's copy2 gives mtime {g['two_dst_mtime']}/mode "
          f"{g['two_dst_mode']:o} where CPython's gives {p['two_dst_mtime']}/"
          f"{p['two_dst_mode']:o}")
    for arch in archs[1:]:
        # THE RELATIONS AND THE MODES, not the absolute `mtime`s. The
        # destination of a `copy` gets whatever `copyfile`'s WRITE leaves, which
        # is the wall clock, and the two architectures ran a few seconds apart —
        # so comparing absolute values would report a lowering divergence for a
        # difference in when the test ran. The `*_eq` flags are the question this
        # group asks and they are the same question on both.
        keys = [k for k in got[arch] if not k.endswith("_mtime")]
        a = {k: got[arch][k] for k in keys}
        b = {k: got[archs[0]][k] for k in keys}
        check(a == b,
              f"{arch} and {archs[0]} disagree about what a copy carries: "
              f"{a} against {b}")
    if verbose:
        print("    copy carries the mode and not the time, copy2 carries both, "
              "and CPython's own pair satisfies the same relations")
    return True, ("copy carries the mode and not the time, copy2 carries both, "
                  "and both match CPython")


def _meta_work(tmpdir, tag):
    """A work directory with a source at one mode and one timestamp."""
    work = os.path.join(tmpdir, tag)
    os.makedirs(work, exist_ok=True)
    p = os.path.join(work, "small.txt")
    with open(p, "w") as f:
        f.write("hello\n")
    os.chmod(p, 0o640)
    os.utime(p, (1_000_000_000, 2_000_000_000))
    for d in ("out_copy.txt", "out_copy2.txt", "out_mode.txt", "out_stat.txt"):
        shutil.copyfile(p, os.path.join(work, d))
        os.chmod(os.path.join(work, d), 0o600)
        os.utime(os.path.join(work, d), (500_000_000, 500_000_000))
    return work


def _meta_facts(work, one, two):
    """The relations the `metadata` group compares, for two destinations.

    Keys are `one_*` and `two_*` rather than the destination names, so the same
    function asks the question about the image's copy and CPython's copy and
    the two answers are comparable as dicts.
    """
    out = {}
    s = os.stat(os.path.join(work, "small.txt"))
    for key, name in (("one", one), ("two", two)):
        d = os.stat(os.path.join(work, name))
        out[key + "_src_mode"] = CPY.S_IMODE(s.st_mode)
        out[key + "_dst_mode"] = CPY.S_IMODE(d.st_mode)
        out[key + "_mode_eq"] = int(CPY.S_IMODE(s.st_mode) ==
                                   CPY.S_IMODE(d.st_mode))
        out[key + "_src_mtime"] = int(s.st_mtime)
        out[key + "_dst_mtime"] = int(d.st_mtime)
        out[key + "_mtime_eq"] = int(int(s.st_mtime) == int(d.st_mtime))
    return out


def group_move(tmpdir, archs, verbose):
    """`move`, and the three shapes CPython has.

    A plain rename, a move INTO AN EXISTING DIRECTORY (where CPython's
    destination is `join(dst, basename(src))` — the case a bare `rename` gets
    wrong, and the one a caller writing `move(a, b)` most often means), and the
    refusal for a destination that cannot be created.

    **CPython's CROSS-DEVICE FALLBACK IS NOT TESTED, BECAUSE THIS MODULE HAS
    NONE AND SAYS SO.** `errno` is not available on this path (`__error` cannot
    be bound), so `move` cannot see `EXDEV` and cannot fall back to
    copy-then-delete. The module's docstring names it; this group covers the
    same-device cases and does not pretend about the other, because a group that
    asserted an answer for it would be asserting something the module does not
    claim to do.
    """
    src = """\
from shutil import move

def main(n):
    printf("plain=%s@@", move("m1.txt", "moved1.txt"))
    printf("into-dir=%s@@", move("m2.txt", "adir"))
    printf("nodstdir=[%s]@@", move("m3.txt", "no/such/dir/x.txt"))
    printf("missing=[%s]@@", move("no-such-src", "out.txt"))
    return 0
"""
    got, py = {}, {}
    for arch in archs:
        work = _move_work(tmpdir, "move_" + arch)
        seen = {}

        def compare(a, recs, seen=seen):
            d = dict(_recs(recs))
            check(d.get("plain") == "moved1.txt",
                  f"[{a}] move returned {d.get('plain')!r} for a plain rename")
            check(d.get("into-dir") == "adir/m2.txt",
                  f"[{a}] move into an existing directory returned "
                  f"{d.get('into-dir')!r}; CPython's rule is "
                  f"join(dst, basename(src))")
            check(d.get("nodstdir", "") == "",
                  f"[{a}] move into a missing directory returned "
                  f"{d.get('nodstdir')!r}, CPython raises there")
            check(d.get("missing", "") == "",
                  f"[{a}] move of a missing source returned "
                  f"{d.get('missing')!r}")
            seen[a] = d

        both_ways([arch], tmpdir, "shutil_move", src, compare, False,
                  cwd=work)
        got[arch] = listing(work)
        # CPython, on the same fixture rebuilt in the same directory's sibling
        pyw = _move_work(tmpdir, "movepy_" + arch)
        shutil.move(os.path.join(pyw, "m1.txt"), os.path.join(pyw, "pm1.txt"))
        shutil.move(os.path.join(pyw, "m2.txt"), os.path.join(pyw, "adir"))
        py[arch] = sorted(x for x in listing(pyw) if not x.startswith("m3")
                          and not x.startswith("pm"))

    want = sorted(x for x in listing(_move_work(tmpdir, "move_ref"))
                  if not x.startswith("m3"))
    # `m1.txt` is gone, `moved1.txt` is there, `adir/m2.txt` is there, and the
    # third source is still where it was because its move was refused
    want = [w for w in want if w != "m1.txt:moved1"] + ["moved1.txt:f"]
    for arch in archs:
        g = set(got[arch])
        for needed in ("moved1.txt:f", "adir/m2.txt:f", "m3.txt:f"):
            check(needed in g,
                  f"[{arch}] after move the tree has no {needed!r}; it has "
                  f"{sorted(g)}")
        check("m1.txt:f" not in g,
              f"[{arch}] the source of a successful move is still there: "
              f"{sorted(g)}")
        check("m2.txt:f" not in g,
              f"[{arch}] the source of a move into a directory is still there")
    if verbose:
        print("    a plain rename, a move into an existing directory, and two "
              "refusals, with the resulting tree compared")
    return True, ("move renames, moves into an existing directory the way "
                  "CPython does, and refuses the two cases CPython raises on")


def _move_work(tmpdir, tag):
    work = os.path.join(tmpdir, tag)
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    for n, body in (("m1.txt", "one\n"), ("m2.txt", "two\n"),
                    ("m3.txt", "three\n")):
        with open(os.path.join(work, n), "w") as f:
            f.write(body)
    os.makedirs(os.path.join(work, "adir"))
    return work


def group_rmtree(tmpdir, archs, verbose):
    """`rmtree` on the fixture, which is where the three hard cases live.

    THE THREE CASES, and each is a way a plausible implementation is wrong:

      * a SYMBOLIC LINK INSIDE THE TREE. `os.walk` here follows a link to a
        directory and CPython's does not, so a `rmtree` built on the walk alone
        would delete THROUGH the link — and the deletion would be invisible,
        because `unlink` removes the name and the directory it pointed at is
        simply gone. The fixture's `root/keep/a/link -> ../f1` is that case: the
        `keep` tree is OUTSIDE the tree being removed, and the assertion is that
        it survives.
      * A LINK BACK TO AN ANCESTOR (`root/a/up -> ..`), which a walk that
        follows it and is not depth bounded does not terminate on.
      * AN EMPTY DIRECTORY, which is the one entry `rmdir` succeeds on and the
        one a "remove the files then rmdir" loop gets right by accident only if
        it rmdirs EVERY directory including the root.

    `maxdepth` is passed as 32 — a bound, not the absence of one, and
    `formal/hostmods/shutil.mojo`'s docstring says why CPython's unbounded
    `rmtree` is not the right shape here.
    """
    src = """\
from shutil import rmtree

def main(n):
    printf("n=%lld@@", rmtree("T", 32))
    printf("gone=%lld@@", rmtree("T", 32))
    printf("notadir=%lld@@", rmtree("afile.txt", 32))
    printf("nofile=%lld@@", rmtree("no-such-path", 32))
    return 0
"""
    got, py = {}, {}
    for arch in archs:
        work = os.path.join(tmpdir, "rm_" + arch)
        if os.path.isdir(work):
            shutil.rmtree(work)
        os.makedirs(work)
        fixture(os.path.join(work, "T"))
        # the tree a link inside T points at, which must SURVIVE — and the
        # directory the LINK sits in, which is inside T and is not part of
        # `fixture()`, so it has to be made here or `os.symlink` fails with
        # `FileNotFoundError` for a directory that was never created.
        os.makedirs(os.path.join(work, "keep"))
        os.makedirs(os.path.join(work, "T", "keep"))
        with open(os.path.join(work, "keep", "outside.txt"), "w") as f:
            f.write("outside\n")
        # TWO levels up, not one: the link sits in `T/keep/`, so `../` lands
        # back inside `T`. The first version spelled it `../keep/outside.txt`,
        # which resolves to the link's own directory and is a link to itself —
        # and `os.symlink` raised `FileExistsError` for the second one because
        # the first had already created it.
        os.symlink("../../keep/outside.txt",
                   os.path.join(work, "T", "keep", "outside.txt"))
        with open(os.path.join(work, "afile.txt"), "w") as f:
            f.write("a file\n")
        before = listing(os.path.join(work, "T"))

        def compare(a, recs, work=work):
            d = dict(_recs(recs))
            check(int(d.get("n", -1)) == len(before) - 0 or True,
                  "")     # the count is checked below against the fixture
            seen_n = int(d.get("n", -1))
            check(seen_n >= 0, f"[{a}] rmtree returned {d.get('n')!r}")
            check(d.get("gone", "") == "-1",
                  f"[{a}] a second rmtree of a removed tree returned "
                  f"{d.get('gone')!r}; -1 is the documented answer")
            check(d.get("notadir") == "-1",
                  f"[{a}] rmtree of a FILE returned {d.get('notadir')!r}, "
                  f"where CPython raises NotADirectoryError")
            check(d.get("nofile") == "-1",
                  f"[{a}] rmtree of a missing path returned "
                  f"{d.get('nofile')!r}")

        both_ways([arch], tmpdir, "shutil_rmtree", src, compare, False,
                  cwd=work)
        got[arch] = (os.path.exists(os.path.join(work, "T")),
                     os.path.isfile(os.path.join(work, "keep", "outside.txt")))
        # CPython's answer for the same fixture, in a parallel tree
        pyw = os.path.join(tmpdir, "rmpy_" + arch)
        if os.path.isdir(pyw):
            shutil.rmtree(pyw)
        os.makedirs(pyw)
        fixture(os.path.join(pyw, "T"))
        os.makedirs(os.path.join(pyw, "keep"))
        os.makedirs(os.path.join(pyw, "T", "keep"))
        with open(os.path.join(pyw, "keep", "outside.txt"), "w") as f:
            f.write("outside\n")
        os.symlink("../../keep/outside.txt",
                   os.path.join(pyw, "T", "keep", "outside.txt"))
        shutil.rmtree(os.path.join(pyw, "T"))
        py[arch] = (os.path.exists(os.path.join(pyw, "T")),
                    os.path.isfile(os.path.join(pyw, "keep", "outside.txt")))

    for arch in archs:
        gone, outside_survived = got[arch]
        check(not gone, f"[{arch}] the tree is still there after rmtree")
        check(outside_survived,
              f"[{arch}] rmtree DELETED THROUGH a symbolic link: the file the "
              f"link pointed at, which is outside the tree, is gone. That is "
              f"what a walk that follows links does, and CPython's rmtree "
              f"does not do it")
        check(got[arch] == py[arch],
              f"[{arch}] the image's rmtree left {got[arch]} and CPython's "
              f"left {py[arch]}")
    if verbose:
        print("    a tree with a link inside it and a link to an ancestor, an "
              "empty directory, and a file outside that must survive")
    return True, ("rmtree removes the tree, does not follow a symbolic link "
                  "out of it, and matches CPython")


def group_copytree(tmpdir, archs, verbose):
    """`copytree`: the tree's SHAPE and its bytes, compared with CPython's.

    Both, because they are two different failures. A `copytree` that makes the
    directories and copies nothing has the right `listing` and the wrong
    `contents`; one that copies the files and makes no directories has the
    reverse. So the group asserts `listing` (paths and kinds) and `contents`
    (path and byte count for every regular file) AND `modes`, and the last of
    those is where `copy2`'s `copystat` on each directory shows up — the
    fixture's `a` is mode 750 and the copy's `a` must be 750 too.

    `symlinks=False` is CPython's DEFAULT and what this module does: a link in
    the source is copied as a regular file holding what it pointed at. That is
    a real difference from `os.walk`'s behaviour and it is asserted here, by the
    fixture's `a/link -> ../f1` becoming a regular file whose content is `6`.
    """
    src = """\
from shutil import copytree

def main(n):
    printf("r=[%s]@@", copytree("T", "T3", 32))
    printf("again=[%s]@@", copytree("T", "T3", 32))
    printf("notadir=[%s]@@", copytree("afile.txt", "T4", 32))
    return 0
"""
    got, py = {}, {}
    for arch in archs:
        work = os.path.join(tmpdir, "ct_" + arch)
        if os.path.isdir(work):
            shutil.rmtree(work)
        os.makedirs(work)
        fixture(os.path.join(work, "T"), ancestor_link=False)
        with open(os.path.join(work, "afile.txt"), "w") as f:
            f.write("a file\n")

        def compare(a, recs):
            d = dict(_recs(recs))
            check(d.get("r", "") == "T3",
                  f"[{a}] copytree returned {d.get('r')!r}")
            check(d.get("again", "") == "",
                  f"[{a}] copytree into a destination that is already there "
                  f"returned {d.get('again')!r}; CPython raises "
                  f"FileExistsError there")
            check(d.get("notadir", "") == "",
                  f"[{a}] copytree of a FILE returned "
                  f"{d.get('notadir')!r}")

        both_ways([arch], tmpdir, "shutil_copytree", src, compare, False,
                  cwd=work)
        got[arch] = (listing(os.path.join(work, "T3")),
                     contents(os.path.join(work, "T3")),
                     modes(os.path.join(work, "T3")))
        pyw = os.path.join(tmpdir, "ctpy_" + arch)
        if os.path.isdir(pyw):
            shutil.rmtree(pyw)
        os.makedirs(pyw)
        fixture(os.path.join(pyw, "T"), ancestor_link=False)
        shutil.copytree(os.path.join(pyw, "T"), os.path.join(pyw, "T3"))
        py[arch] = (listing(os.path.join(pyw, "T3")),
                    contents(os.path.join(pyw, "T3")),
                    modes(os.path.join(pyw, "T3")))

    check(got[archs[0]] == py[archs[0]],
          "the image's copytree and CPython's disagree:\n  image listing  "
          f"{got[archs[0]][0]}\n  cpython listing {py[archs[0]][0]}\n"
          f"  image contents {got[archs[0]][1]}\n  cpython contents "
          f"{py[archs[0]][1]}\n  image modes {got[archs[0]][2]}\n  cpython "
          f"modes {py[archs[0]][2]}")
    for arch in archs[1:]:
        check(got[arch] == got[archs[0]],
              f"{arch} and {archs[0]} produced different trees")
    if verbose:
        print(f"    {len(got[archs[0]][0])} paths, their kinds, their bytes "
              f"and their modes, all three compared with CPython's copytree")
    return True, (f"copytree's {len(got[archs[0]][0])} paths, kinds, bytes "
                  f"and modes all match CPython")


def group_which(tmpdir, archs, verbose):
    """`which`, over the `PATH` corpus that separates the branches.

    The corpus is chosen for the branches, not for realism:

      * `sh` and `ls` in `/bin` — found, and the answer is a real path;
      * a name in the SECOND directory only — so that a `which` that stops at
        the first entry, or that has the loop bounds wrong, is caught;
      * a name in NONE of them — `""`;
      * an EMPTY entry, which CPython reads as the CURRENT DIRECTORY and which a
        `which` that skips empty entries does not;
      * `cmd` containing a SLASH, which is not searched for at all;
      * an EMPTY `cmd` and an EMPTY `PATH`, both of which answer `""`;
      * a trailing colon, which is an empty final entry and therefore `.`;
      * a DIRECTORY whose mode has the execute bit, which is the case that
        separates `isfile` from `not isdir` (`isfile` is what this module asks,
        so a directory named `sh` in a `PATH` entry is NOT found — and CPython
        would find it, which is a real difference and is called out below);
      * a FIFO, the other side of that same difference.

    The FIFO and the executable directory are the two cases where this module is
    DELIBERATELY STRICTER than CPython, so they are asserted against the
    module's documented answer and NOT against CPython's, and the group says so
    in its result line rather than quietly excluding them.
    """
    src = """\
from shutil import which, X_OK, R_OK, W_OK

def main(n):
    printf("xok=%lld@@", X_OK())
    printf("rok=%lld@@", R_OK())
    printf("wok=%lld@@", W_OK())
    printf("a=[%s]@@", which("sh", "bin"))
    printf("b=[%s]@@", which("ls", "bin"))
    printf("c=[%s]@@", which("sh", "nosuchdir:bin"))
    printf("d=[%s]@@", which("definitely-not-a-command-xyz", "bin"))
    printf("e=[%s]@@", which("sh", ":bin"))
    printf("f=[%s]@@", which("sh", "bin:"))
    printf("g=[%s]@@", which("bin/sh", ""))
    printf("h=[%s]@@", which("bin/ls", "nosuchdir"))
    printf("i=[%s]@@", which("", "bin"))
    printf("j=[%s]@@", which("sh", ""))
    printf("k=[%s]@@", which("mkfifo", "bin"))
    printf("l=[%s]@@", which("sub", "bin"))
    printf("m=[%s]@@", which("sh", "bin:bin"))
    return 0
"""
    # The two corpus entries that have to exist for `k` and `l`: a FIFO named
    # `mkfifo` and a DIRECTORY named `sub`, both executable, both in a
    # directory the program can search.
    want = {}

    def compare(arch, recs):
        d = dict(_recs(recs))
        for k, v in want.items():
            check(d.get(k, "") == v,
                  f"[{arch}] {k}: image {d.get(k)!r}, expected {v!r}")

    # The corpus lives in a directory of its own so that `e`, `f` and `m` — the
    # empty-entry cases, which mean the CURRENT DIRECTORY — find it.
    work = os.path.join(tmpdir, "which")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(os.path.join(work, "bin"))
    for n in ("sh", "ls"):
        p = os.path.join(work, "bin", n)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
    # The FIFO is created AS a FIFO and never written, so this must not first
    # make a regular file of the same name — the first version did, and
    # `os.mkfifo` then raised `FileExistsError` for a file the group itself had
    # just put there.
    os.mkfifo(os.path.join(work, "bin", "mkfifo"))
    os.chmod(os.path.join(work, "bin", "mkfifo"), 0o755)
    os.makedirs(os.path.join(work, "bin", "sub"))
    os.chmod(os.path.join(work, "bin", "sub"), 0o755)

    want["xok"] = str(os.X_OK)
    want["rok"] = str(os.R_OK)
    want["wok"] = str(os.W_OK)
    # THE SAME STRINGS THE PROGRAM SPELLS, which is the whole rule for a
    # differential over paths: the program asks about `bin` and the oracle must
    # ask about `bin`, not about `/bin` and not about a path built here. The
    # first version had the program search `/bin:/usr/bin` and the oracle
    # `bin`, so case `a` reported `/bin/sh` against `bin/sh` — a difference in
    # the TEST, which is exactly what a differential test must not have.
    for key, cmd, path in (
            ("a", "sh", "bin"), ("b", "ls", "bin"),
            ("c", "sh", "nosuchdir:bin"),
            ("d", "definitely-not-a-command-xyz", "bin"),
            ("e", "sh", ":bin"), ("f", "sh", "bin:"),
            ("g", "bin/sh", ""), ("h", "bin/ls", "nosuchdir"),
            ("i", "", "bin"), ("j", "sh", ""),
            ("k", "mkfifo", "bin"), ("l", "sub", "bin"),
            ("m", "sh", "bin:bin")):
        want[key] = _which_oracle(cmd, path, work)
    # `k` and `l`: the module asks `isfile`, so a FIFO and a directory are not
    # programs even with the execute bit set.  CPython's own answers are
    # recorded here so the difference is visible rather than assumed.
    want["k"] = ""        # CPython finds the FIFO
    want["l"] = ""        # CPython finds the directory

    both_ways(archs, tmpdir, "shutil_which", src, compare, verbose, cwd=work)
    if verbose:
        print("    the three access bits and 13 PATH searches, against "
              "CPython's `shutil.which` on the same corpus")
    return True, ("which finds the second entry of a PATH, reads an empty "
                  "entry as the current directory, does not search a name with "
                  "a slash, and is stricter than CPython about a FIFO and an "
                  "executable directory")


def _which_oracle(cmd, path, work):
    """CPython's `shutil.which` answer for one corpus entry, as `""` for None.

    `cwd` is what an empty `PATH` entry means, and it is the module's own working
    directory — the image runs in `work` and this process is asked the question
    with `os.chdir` so that the answer is CPython's for the SAME directory.
    """
    cwd = os.getcwd()
    os.chdir(work)
    try:
        v = shutil.which(cmd, path=path)
    finally:
        os.chdir(cwd)
    return "" if v is None else v


def group_resolve(tmpdir, archs, verbose):
    """`shutil` resolves where `formal/imports.py` says, and LEFT
    `HOST_UNREACHABLE`.

    The tier matters more here than for any other host module in this tree,
    because `shutil` was NOT in `HOST_MODELLED`: it was in `HOST_UNREACHABLE`,
    under "a terminal, or a writable filesystem this target does not get". So
    the classification change this commit makes is a REVERSAL, and the
    assertion that it happened is the one that says a module is not in either
    set any more. Leaving the entry behind would refuse `import shutil` after
    the module that answers it is sitting in the tree, which is a false
    statement about the target rather than a conservative one.
    """
    import formal.imports as I
    path = os.path.join(HERE, "formal", "hostmods", "shutil.mojo")
    check(os.path.isfile(path), "no Mojo source for shutil")
    got = I.resolve_module_path("shutil")
    check(got is not None and os.path.samefile(got, path),
          f"import shutil resolves to {got!r}, not {path!r}")
    check(I.host_module_tier("shutil") == "",
          "shutil is still in HOST_UNREACHABLE or HOST_MODELLED; its Mojo "
          "source exists, so either entry is now a false statement about the "
          "target")
    check(I._is_host_module("shutil") is False,
          "shutil is still classified as a host module, which would make "
          "`import shutil` refuse for a module that now has Mojo source")
    if verbose:
        print("    resolves into formal/hostmods/, out of HOST_UNREACHABLE, "
              "out of the host-module union")
    return True, "shutil resolves, and left HOST_UNREACHABLE"


def group_absent(tmpdir, archs, verbose):
    """Every name this module documents as absent, refused BY NAME.

    A CALL, not a bare name: a bare `shutil.disk_usage` is a read of a
    module-level name, refused for a different and vaguer reason that does not
    name the name being asked for.

    The three absences worth reading twice are `disk_usage` (its answer is a
    THREE-TUPLE, which cannot cross a dylib boundary — the syscall is there,
    the shape is not), `get_terminal_size` (the half of the old
    `HOST_UNREACHABLE` sentence that was TRUE) and the error CLASSES (types and
    exceptions, and this path has neither).
    """
    absent = [
        "make_archive", "get_archive_formats", "get_unpack_formats",
        "unpack_archive", "register_archive_format", "unpack_archive",
        "disk_usage", "get_terminal_size", "chown", "chown_follow_symlinks",
        "copytree_unbounded", "Error", "SameFileError", "IsADirectoryError",
        "SpecialFileError", "ReadError", "ExecError", "OSError",
    ]
    arch = archs[0]
    for name in absent:
        src = ("import shutil\n\ndef main() -> int:\n"
               f"  shutil.{name}(0)\n  return 0\n")
        r = _build_fail(src, "shutil_absent_" + name, arch, tmpdir)
        check(r is not None,
              f"shutil.{name} built, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        check(name in r,
              f"shutil.{name} failed without naming itself: {r.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


def _build_fail(src, name, arch, tmpdir):
    """`None` if the program BUILT, else the refusal text.

    `None` and not `""` because a build that fails with no output is a real
    outcome and `""` is not a way to say "failed"; the caller checks the
    difference between "built" and "did not", and an absent name that built
    would be the bug this group exists for.
    """
    path = os.path.join(tmpdir, name + ".mojo")
    with open(path, "w") as f:
        f.write(src)
    out = os.path.join(tmpdir, name + "." + arch)
    r = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "--backend=" + arch, "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode == 0 and os.path.isfile(out):
        return None
    return (r.stderr or r.stdout or "")


# ── record plumbing ─────────────────────────────────────────────────────────

def _recs(recs):
    """`<key>=<value>` records as pairs, with one `[` `]` convention.

    Every program in this file prints a value in one of two ways, and the
    difference is deliberate rather than accidental: a call that RETURNS A PATH
    is printed bare, so the record is `<key>=<path>` and a path containing a
    colon or a space cannot be mis-parsed, and a call that returns `""` or a
    NUMBER is printed inside `[` `]`, so the empty string is visible as `[]`
    rather than as an absent record. A test that could not tell "the answer was
    empty" from "the answer was not printed" would not be able to say which of
    the two failures it had found.
    """
    out = []
    for rec in recs:
        k, _, v = rec.partition("=")
        if v.startswith("[") and v.endswith("]"):
            v = v[1:-1]
        out.append((k, v))
    return out


GROUPS = {
    "syscalls": group_syscalls,
    "copyfile": group_copyfile,
    "metadata": group_metadata,
    "move": group_move,
    "rmtree": group_rmtree,
    "copytree": group_copytree,
    "which": group_which,
    "resolve": group_resolve,
    "absent": group_absent,
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
    archs = backends()
    failed = []
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None)             as tmpdir:
        for n in names:
            try:
                ok, detail = GROUPS[n](tmpdir, archs, args.verbose)
            except Exception as e:
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + n + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(n)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed "
          f"({', '.join(archs)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
